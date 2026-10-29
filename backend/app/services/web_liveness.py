"""Thử thách một lần trong RAM; không giữ ảnh hoặc ghi embedding ra log/DB."""

from collections import OrderedDict
from dataclasses import dataclass, field
import secrets
from threading import Lock
from time import monotonic

import numpy as np


ACTION_MESSAGES = {
    "center": "Nhìn thẳng và giữ yên khuôn mặt",
    "left": "Quay đầu nhẹ sang trái của bạn, không quay ngang hẳn",
    "right": "Quay đầu nhẹ sang phải của bạn, không quay ngang hẳn",
    "up": "Ngẩng đầu nhẹ",
    "down": "Cúi đầu nhẹ",
}


@dataclass
class Challenge:
    owner: tuple
    actions: tuple
    created: float
    step: int = 0
    step_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    sequence: int = -1
    last_seen: float | None = None
    hold_started: float | None = None
    hits: int = 0
    student_id: int | None = None
    anchor: np.ndarray | None = None
    neutral: tuple | None = None
    hashes: set = field(default_factory=set)


class WebLivenessStore:
    def __init__(self, settings, *, clock=monotonic, max_challenges=128, choose=None):
        self.settings = settings
        self.clock = clock
        self.max_challenges = max_challenges
        self.choose = choose or (lambda: secrets.SystemRandom().sample(("left", "right", "up", "down"), 3))
        self._items = OrderedDict()
        self._lock = Lock()

    def _expire(self, now):
        for key, item in list(self._items.items()):
            if now - item.created > self.settings.web_liveness_ttl_seconds:
                del self._items[key]

    def _view(self, challenge_id, item, message=None):
        action = item.actions[item.step]
        instruction = ACTION_MESSAGES[action]
        if action in {"left", "right", "up", "down"}:
            angle = (self.settings.web_liveness_yaw_degrees if action in {"left", "right"}
                     else self.settings.web_liveness_pitch_degrees)
            instruction += f" (khoảng {angle:g}°)"
        return {
            "status": "pending", "challenge_id": challenge_id, "step_token": item.step_token,
            "action": item.actions[item.step], "step": item.step,
            "total_steps": len(item.actions), "sequence": item.sequence + 1,
            "expires_in_seconds": max(0, self.settings.web_liveness_ttl_seconds - (self.clock() - item.created)),
            "message": message or instruction,
        }

    def _frame_error(self, item, now, *, step_token, sequence, digest):
        if sequence != item.sequence + 1 or not secrets.compare_digest(step_token or "", item.step_token):
            return "Khung hình sai thứ tự hoặc bước đã hết hiệu lực. Vui lòng quét lại."
        last_valid = item.last_seen if item.last_seen is not None else item.created
        if now - last_valid > self.settings.web_liveness_max_gap_seconds:
            return "Luồng camera bị gián đoạn hoặc mất mặt quá lâu. Vui lòng quét lại."
        if digest in item.hashes:
            return "Khung hình bị lặp. Vui lòng dùng camera trực tiếp."
        if len(item.hashes) >= 256:
            return "Quá nhiều khung hình trong thử thách. Vui lòng quét lại."
        return None

    def retry_frame(self, challenge_id, owner, *, step_token, sequence, digest, message):
        """Frame lỗi không chứng minh liveness; không gia hạn khoảng mất mặt/TTL."""
        with self._lock:
            now = self.clock()
            self._expire(now)
            item = self._items.get(challenge_id)
            if item is None or item.owner != owner:
                return {"status": "failed", "message": "Thử thách hết hạn hoặc không hợp lệ. Vui lòng quét lại."}
            error = self._frame_error(item, now, step_token=step_token, sequence=sequence, digest=digest)
            if error:
                del self._items[challenge_id]
                return {"status": "failed", "message": error}
            item.sequence = sequence
            item.hashes.add(digest)
            item.hold_started, item.hits = None, 0
            return self._view(challenge_id, item, f"{message}. {ACTION_MESSAGES[item.actions[item.step]]}.")

    def start(self, owner):
        with self._lock:
            now = self.clock()
            self._expire(now)
            # Một luồng cho mỗi user/session; mở lại camera hủy thử thách cũ.
            for key, value in list(self._items.items()):
                if value.owner == owner:
                    del self._items[key]
            if len(self._items) >= self.max_challenges:
                self._items.popitem(last=False)
            actions = ["center"]
            for action in self.choose():
                actions.extend((action, "center"))
            challenge_id = secrets.token_urlsafe(32)
            item = Challenge(owner, tuple(actions), now)
            self._items[challenge_id] = item
            return self._view(challenge_id, item)

    def valid(self, challenge_id, owner):
        with self._lock:
            self._expire(self.clock())
            item = self._items.get(challenge_id)
            return item is not None and item.owner == owner

    def cancel(self, challenge_id, owner):
        with self._lock:
            item = self._items.get(challenge_id)
            if item is not None and item.owner == owner:
                del self._items[challenge_id]

    def observe(self, challenge_id, owner, *, step_token, sequence, digest, result, student_id):
        with self._lock:
            now = self.clock()
            self._expire(now)
            item = self._items.get(challenge_id)

            def failed(message):
                if item is not None and item.owner == owner:
                    self._items.pop(challenge_id, None)
                return {"status": "failed", "message": message}

            if item is None or item.owner != owner:
                return failed("Thử thách hết hạn hoặc không hợp lệ. Vui lòng quét lại.")
            error = self._frame_error(item, now, step_token=step_token, sequence=sequence, digest=digest)
            if error:
                return failed(error)
            if result.pose is None or not np.isfinite([result.pose.yaw, result.pose.pitch]).all():
                return failed("Chưa đo được góc khuôn mặt. Hãy nhìn thẳng, tăng ánh sáng và thử lại.")
            vector = np.asarray(result.embedding, dtype=np.float32)
            if vector.shape != (128,) or not np.isfinite(vector).all():
                return failed("Engine Face ID không phù hợp với xác minh người thật.")
            if item.anchor is not None:
                distance = float(np.linalg.norm(vector - item.anchor))
                if student_id != item.student_id or distance > self.settings.web_liveness_identity_distance:
                    return failed("Khuôn mặt thay đổi trong lúc xác minh. Vui lòng quét lại.")
            else:
                item.anchor = vector.copy()
                item.student_id = student_id
            item.sequence = sequence
            item.hashes.add(digest)
            # Không tính request dồn dập thành bằng chứng theo thời gian.
            if item.last_seen is not None and now - item.last_seen < self.settings.web_liveness_min_interval_seconds:
                return self._view(challenge_id, item)
            item.last_seen = now
            yaw, pitch = result.pose.yaw, result.pose.pitch
            if item.neutral is None:
                matched = abs(yaw) <= 12 and abs(pitch) <= 18
            else:
                yaw -= item.neutral[0]
                pitch -= item.neutral[1]
                action = item.actions[item.step]
                yaw_limit = self.settings.web_liveness_yaw_degrees
                pitch_limit = self.settings.web_liveness_pitch_degrees
                matched = {
                    "center": abs(yaw) <= 10 and abs(pitch) <= 10,
                    "left": yaw <= -yaw_limit and abs(pitch) <= 25,
                    "right": yaw >= yaw_limit and abs(pitch) <= 25,
                    "up": pitch <= -pitch_limit and abs(yaw) <= 20,
                    "down": pitch >= pitch_limit and abs(yaw) <= 20,
                }[action]
            if not matched:
                item.hold_started, item.hits = None, 0
            else:
                item.hold_started = now if item.hold_started is None else item.hold_started
                item.hits += 1
                if item.hits >= self.settings.web_liveness_min_hits and now - item.hold_started >= self.settings.web_liveness_hold_seconds:
                    if item.neutral is None:
                        item.neutral = (result.pose.yaw, result.pose.pitch)
                    item.step += 1
                    item.hold_started, item.hits = None, 0
                    item.step_token = secrets.token_urlsafe(24)
                    if item.step == len(item.actions):
                        # Tiêu thụ nguyên tử: request đua/replay không thể dùng lại kết quả pass.
                        del self._items[challenge_id]
                        return {"status": "passed", "message": "Đã xác minh người thật"}
            message = "Đúng góc, giữ yên khuôn mặt thêm một chút" if matched and item.hits else None
            return self._view(challenge_id, item, message)
