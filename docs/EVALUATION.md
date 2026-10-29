# Kiểm chứng bản tích hợp liveness web — 29/10/2026

## Môi trường và kết quả phần mềm

Windows x64, Python 3.13.17 trong `.venv313`, dlib ResNet 128D, OpenCV 4.14,
ONNX Runtime CPU. Hai artifact MiniFASNet từ release đã được kiểm SHA-256 theo
`ai_pipeline/minifasnet.py`; đã nạp và chạy suy luận thực trên ảnh tổng hợp.

```powershell
.\.venv313\Scripts\python.exe -m pytest -q --run-browser
.\.venv313\Scripts\python.exe -m ruff check .
node --check frontend/app.js
```

- 122 test pass, gồm 7 test Chrome headless với webcam tổng hợp; không chụp camera thật.
- Lint và kiểm tra cú pháp JavaScript pass.
- Còn một StarletteDeprecationWarning ở thư viện TestClient/httpx; không làm test thất bại.
- Backend thật `/demo/attendance` trả HTTP 200; status báo MiniFASNet ready,
  web_liveness_ready=true và preprocessing/liveness enforce trong cấu hình local.

Đã kiểm tra: PAD trước embedding/tăng cường, cả hai model phải đạt ngưỡng, thiếu
model không pass, cùng danh tính, nonce/sequence/hash mới, đủ thời gian, hết hạn,
đổi người, đổi owner, reset, consume một lần, không ghi DB/ảnh khi chưa pass,
idempotency đúng phạm vi, thu hồi consent, giao thức web, tọa độ xoay/roll và không
báo thành công khi chưa lưu điểm danh. Quy tắc nghiệp vụ cũ vẫn có regression test.

Đã bổ sung kiểm thử YuNet nạp/suy luận CPU, checksum, map box từ ảnh giới hạn kích
thước về nguồn, giữ box HOG và từ chối mặt thứ hai. CLAHE ở nhánh tìm mặt không
thay pixel PAD. Kiểm thử HTTP hoàn thành thử thách 7 bước qua 28 frame, trong đó
7 frame mất mặt: giữ bước đã hoàn thành, reset hold hiện tại, không ghi DB trước
frame cuối. Retry vẫn chặn nonce/sequence/hash sai, đổi người và mất mặt quá gap.
Chrome xác nhận client giữ challenge và dùng sequence mới sau frame mất mặt.

Smoke test bổ sung dùng ba ảnh ví dụ công khai từ
[face_recognition](https://github.com/ageitgey/face_recognition/tree/master/examples),
chỉ giữ trong RAM: 42 biến thể roll/độ sáng, HOG và hybrid đều thấy đúng một mặt
ở 40/42 trường hợp, các box HOG có sẵn được giữ nguyên. Bộ nhỏ này không cho thấy
cải thiện tỷ lệ phát hiện và không mô phỏng được yaw 3D hay webcam của người dùng;
không dùng nó để công bố giảm tỷ lệ mất mặt. YuNet đã nạp được ở backend local,
status báo hybrid/yunet_ready=true, profile embedding hiện hữu giữ nguyên.

## Những gì chưa được đo

Chưa có dataset ảnh camera được phép sử dụng cho môi trường mục tiêu. Vì vậy chưa
có APCER/BPCER, FAR/FRR, tỷ lệ pass thử thách của người thật hay p95 trên camera
vật lý. Test vector/ảnh tổng hợp và UI với API mô phỏng chỉ chứng minh logic,
không chứng minh khả năng chống ảnh in/video trên phần cứng thực tế.

Chưa nghiệm thu chống camera ảo, deepfake tương tác, mặt nạ 3D hoặc client bị kiểm
soát. Webcam RGB và thử thách chuyển động không cung cấp chứng thực phần cứng.
Camera-token endpoint là kênh worker tin cậy, dùng PAD + xác nhận nhiều frame,
không phải giao thức thử thách tương tác của web. Không đưa token camera vào client
web; trước triển khai công khai cần thay xác thực demo và quản trị khóa thiết bị.

## Nghiệm thu thực địa tiếp theo

Dùng quy trình và CSV trong [FACE_ANALYSIS.md](FACE_ANALYSIS.md), đo riêng ảnh in,
ảnh in bị uốn/đục mắt, video trên điện thoại/tablet/LCD, nhiều mức sáng/tần số và
webcam chưa thấy; đồng thời đo người thật đeo kính, góc/sáng khác nhau. Dữ liệu
validation/test phải tách người/phiên, không dùng ảnh đăng ký để đánh giá nhận diện.

Chạy `scripts/evaluate_liveness.py` cho PAD, đóng băng ngưỡng trên validation trước
khi đánh giá test. Kiểm tra toàn bộ thử thách trên web riêng, tính theo phiên thay
vì coi các frame liên tiếp là mẫu độc lập. Chỉ duyệt model sau khi kết quả phù hợp
mục tiêu của đơn vị; cờ allow_pretrained local không thay thế bước nghiệm thu này.
