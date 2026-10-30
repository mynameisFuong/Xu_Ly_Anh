"""Session-disjoint face recognition ablations; reports contain no face vectors."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_pipeline.preprocessing import PreprocessingOptions
from ai_pipeline.recognition import FaceRecognizer, match_embedding


@dataclass(frozen=True)
class Sample:
    path: Path
    subject: str
    session: str
    role: str
    partition: str
    condition: str = "normal"
    variant: str = "original"


def load_manifest(path: Path) -> list[Sample]:
    """Reject session/source leakage before selecting validation or test samples."""
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = []
    subjects = defaultdict(set)
    sessions = defaultdict(lambda: defaultdict(set))
    sources = {}
    content = {}
    for item in data["samples"]:
        sample = Sample(path=(path.parent / item["path"]).resolve(), subject=str(item["subject"]),
                        session=str(item["session"]), role=item["role"], partition=item["partition"],
                        condition=item.get("condition", "normal"), variant=item.get("variant", "original"))
        if sample.role not in {"enroll", "probe", "unknown"} or sample.partition not in {"validation", "test"}:
            raise ValueError("Invalid role or partition")
        if not sample.subject or not sample.session or not sample.path.is_file():
            raise ValueError("Every sample needs an identity, a session and an existing image")
        boundary = (sample.partition, sample.subject, sample.session, sample.role)
        for mapping, key in ((content, sha256(sample.path.read_bytes()).hexdigest()),
                             (sources, str(item.get("source_id", sample.path)))):
            if key in mapping and mapping[key] != boundary:
                raise ValueError("Source image or synthetic variant leaks across roles/sessions/partitions")
            mapping[key] = boundary
        subjects[sample.partition].add(sample.subject)
        sessions[(sample.partition, sample.subject)][sample.role].add(sample.session)
        samples.append(sample)
    if not samples:
        raise ValueError("Manifest contains no samples")
    if subjects["validation"] & subjects["test"]:
        raise ValueError("Validation and test identities must be disjoint")
    for roles in sessions.values():
        if roles["enroll"] & roles["probe"]:
            raise ValueError("Enrollment and probe sessions overlap")
        if roles["unknown"] and (roles["enroll"] or roles["probe"]):
            raise ValueError("An unknown identity cannot have enrollment or known probes")
        if roles["probe"] and not roles["enroll"]:
            raise ValueError("Every known probe identity needs enrollment images")
    return samples


def sample_bytes(sample, max_side=0):
    """Synthetic probes stay linked to their original identity/session/partition."""
    raw = sample.path.read_bytes()
    if sample.variant == "original" and not max_side:
        return raw
    import cv2
    from ai_pipeline.preprocessing import decode_bgr_image, orient_image, rotate_roll

    image = decode_bgr_image(raw)
    if image is None:
        return raw
    if max_side and max(image.shape[:2]) > max_side:
        scale = max_side / max(image.shape[:2])
        image = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    if sample.variant in {"rotate-90", "rotate-180", "rotate-270"}:
        image = orient_image(image, rotation=int(sample.variant.split("-")[1])).image
    elif sample.variant.startswith("roll-"):
        angle = sample.variant.removeprefix("roll-").replace("minus", "-")
        if angle not in {"10", "-10", "20", "-20", "30", "-30"}:
            raise ValueError("Unknown synthetic roll")
        image = rotate_roll(orient_image(image), int(angle)).image
    elif sample.variant == "mirror":
        image = orient_image(image, mirror=True).image
    elif sample.variant == "dark":
        image = np.rint(image * 0.55).astype(np.uint8)
    elif sample.variant == "low-contrast":
        image = np.clip(120 + (image.astype(np.float32) - 120) * 0.4, 0, 255).astype(np.uint8)
    elif sample.variant == "noise":
        image = np.clip(image.astype(np.float32) + np.random.default_rng(42).normal(0, 5, image.shape), 0, 255).astype(np.uint8)
    elif sample.variant == "side-light":
        scale = np.linspace(0.35, 1.0, image.shape[1], dtype=np.float32)[None, :, None]
        image = np.rint(image.astype(np.float32) * scale).astype(np.uint8)
    elif sample.variant == "blur":
        image = cv2.GaussianBlur(image, (7, 7), 1.5)
    elif sample.variant not in {"jpeg", "original"}:
        raise ValueError("Unknown synthetic variant")
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 35 if sample.variant == "jpeg" else 95])
    return encoded.tobytes() if ok else raw


def profile_options(name: str, base: PreprocessingOptions) -> PreprocessingOptions:
    common = replace(base, mode="enforce", shadow_v2=False, shadow_sample_rate=0)
    if name == "legacy":
        return replace(common, mode="off")
    if name == "v1":
        return replace(common, version="v1")
    variants = {
        "v2-geometry": dict(lighting_method="none", denoise_method="off"),
        "v2-gamma": dict(lighting_method="gamma", denoise_method="off"),
        "v2-clahe": dict(lighting_method="clahe", denoise_method="off"),
        "v2-adaptive": dict(lighting_method="adaptive", denoise_method="off"),
        "v2-denoise": dict(lighting_method="adaptive", denoise_method="adaptive"),
        "v2-align": dict(lighting_method="none", denoise_method="off", v2_align_eyes=True),
        "v3-geometry": dict(lighting_method="none", denoise_method="off", v3_dark_rescue=False),
        "v3-adaptive": dict(lighting_method="adaptive", denoise_method="off"),
        "v3-denoise": dict(lighting_method="adaptive", denoise_method="adaptive"),
        "v3-align": dict(lighting_method="none", denoise_method="off", v2_align_eyes=True,
                         v3_dark_rescue=False),
        "retinex": dict(lighting_method="none", denoise_method="off"),
        "tan-triggs": dict(lighting_method="none", denoise_method="off"),
    }
    if name not in variants:
        raise ValueError(f"Unknown ablation: {name}")
    updates = dict(version="v3" if name.startswith("v3-") else "v2",
                   normalize_lighting=True, v2_align_eyes=False)
    updates.update(variants[name])
    return replace(common, **updates)


def experimental_analysis(recognizer, name):
    """Override only the ROI photometric branch; native quality gates still run."""
    from ai_pipeline.analysis import FaceAnalysis
    from ai_pipeline.experiments import multiscale_retinex, tan_triggs

    transform = multiscale_retinex if name == "retinex" else tan_triggs

    class ExperimentalAnalysis(FaceAnalysis):
        @staticmethod
        def _enhance_region(image, box, _metrics, options):
            x, y, w, h = box
            px, py = round(w * options.roi_padding), round(h * options.roi_padding)
            left, top = max(0, x - px), max(0, y - py)
            right, bottom = min(image.shape[1], x + w + px), min(image.shape[0], y + h + py)
            output = image.copy()
            output[top:bottom, left:right] = transform(image[top:bottom, left:right])
            return output, ("experimental-" + name,)

    recognizer._analysis = ExperimentalAnalysis(recognizer, preprocessing=recognizer._analysis.preprocessing)


def cluster_interval(outcomes):
    """Subject-block bootstrap of the macro rejection rate, deterministic seed."""
    grouped = defaultdict(list)
    for subject, failed in outcomes:
        grouped[subject].append(failed)
    rates = np.asarray([np.mean(values) for values in grouped.values()])
    if len(rates) < 2:
        return None
    rng = np.random.default_rng(42)
    bootstrap = np.mean(rng.choice(rates, (1000, len(rates)), replace=True), axis=1)
    return {"macro_rate": float(rates.mean()), "ci95": np.percentile(bootstrap, [2.5, 97.5]).tolist(),
            "independent_subjects": len(rates)}


def threshold_at_far(impostors, target_far):
    """Largest observed distance cutoff with empirical FMR <= target on validation."""
    if not impostors:
        return None
    distances = np.sort(np.asarray(impostors, np.float64))
    allowed = int(np.floor(target_far * len(distances)))
    if allowed >= len(distances):
        return float(distances[-1])
    return float(np.nextafter(distances[allowed], -np.inf))


def evaluate_profile(samples, recognizer, *, threshold=0.52, margin=0.04, target_far=0.01,
                     calibrated_threshold=None, max_side=0):
    templates = defaultdict(list)
    identities = {subject: index for index, subject in enumerate(sorted({s.subject for s in samples}))}
    results = []
    times = []
    preprocessing_times = []
    rejected = Counter()
    operations = Counter()
    enrollment_failures = 0
    for sample in sorted(samples, key=lambda s: s.role != "enroll"):
        image_bytes = sample_bytes(sample, max_side)
        started = perf_counter()
        result = recognizer.extract_single_embedding(image_bytes)
        times.append((perf_counter() - started) * 1000)
        if not result.accepted:
            rejected[(result.reason or "unspecified").split(":", 1)[0]] += 1
        if result.diagnostics:
            operations.update(result.diagnostics.operations)
            if result.diagnostics.preprocessing_ms is not None:
                preprocessing_times.append(result.diagnostics.preprocessing_ms)
        if sample.role == "enroll":
            if result.accepted:
                templates[identities[sample.subject]].append(result.embedding)
            else:
                enrollment_failures += 1
        else:
            results.append((sample, result))
    known = unknown = correct = misidentified = false_identified = 0
    genuine, impostors = [], []
    conditions = defaultdict(Counter)
    outcomes = []
    for sample, result in results:
        is_known = sample.role == "probe"
        known += is_known
        unknown += not is_known
        matched_id = None
        if result.accepted:
            match = match_embedding(result.embedding, templates, threshold=threshold, margin=margin, metric="euclidean")
            matched_id = match.student_id
            for subject_id, vectors in templates.items():
                distance = min(float(np.linalg.norm(result.embedding - vector)) for vector in vectors)
                (genuine if is_known and subject_id == identities[sample.subject] else impostors).append(distance)
        successful = is_known and matched_id == identities[sample.subject]
        correct += successful
        misidentified += is_known and matched_id is not None and not successful
        false_identified += not is_known and matched_id is not None
        conditions[sample.condition]["probes"] += 1
        conditions[sample.condition]["extraction_rejected"] += not result.accepted
        conditions[sample.condition]["known_probes"] += is_known
        conditions[sample.condition]["correct_identification"] += successful
        if is_known:
            outcomes.append((sample.subject, not successful))
    pair_cutoff = threshold_at_far(impostors, target_far) if samples[0].partition == "validation" else calibrated_threshold
    return {
        "model_version": recognizer.model_version,
        "subjects": len(identities), "enrollments": sum(s.role == "enroll" for s in samples),
        "enrollment_failures": enrollment_failures, "known_probes": known, "unknown_probes": unknown,
        "correct_identification": correct, "misidentified_known": misidentified, "false_identified_unknown": false_identified,
        "false_reject_rate": (known - correct) / known if known else None,
        "fpir": false_identified / unknown if unknown else None,
        "fmr": float(np.mean(np.asarray(impostors) <= threshold)) if impostors else None,
        "fnmr": float(np.mean(np.asarray(genuine) > threshold)) if genuine else None,
        "genuine_comparisons": len(genuine), "impostor_comparisons": len(impostors),
        "target_far": target_far, "threshold_at_target_far": pair_cutoff,
        "tar_at_target_far": float(np.mean(np.asarray(genuine) <= pair_cutoff)) if genuine and pair_cutoff is not None else None,
        "known_failure_subject_bootstrap": cluster_interval(outcomes),
        "latency_p50_ms": float(np.percentile(times, 50)), "latency_p95_ms": float(np.percentile(times, 95)),
        "preprocessing_p95_ms": float(np.percentile(preprocessing_times, 95)) if preprocessing_times else None,
        "rejection_reasons": dict(rejected), "operations": dict(operations),
        "by_condition": {key: dict(value) for key, value in conditions.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--partition", choices=("validation", "test"), required=True)
    parser.add_argument("--profiles", nargs="+", default=["legacy", "v1", "v2-geometry", "v2-adaptive"])
    parser.add_argument("--threshold", type=float, default=0.52)
    parser.add_argument("--margin", type=float, default=0.04)
    parser.add_argument("--target-far", type=float, default=0.01)
    parser.add_argument("--calibration", type=Path, help="Validation report from the SAME full manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stress", action="store_true", help="Add deterministic synthetic probe variants; not acceptance data")
    parser.add_argument("--max-side", type=int, default=0, help="Common input resize before all profiles; 0 keeps native resolution")
    args = parser.parse_args()
    if not (0 <= args.target_far < 1 and args.threshold > 0 and args.margin >= 0):
        parser.error("Invalid threshold, margin or target FAR")
    if args.max_side and args.max_side < 160:
        parser.error("max-side must be 0 or at least 160 pixels")
    all_samples = load_manifest(args.manifest)
    samples = [sample for sample in all_samples if sample.partition == args.partition]
    if not samples or not any(s.role != "enroll" for s in samples):
        parser.error("Selected partition needs enrollment/probe or unknown samples")
    if args.stress:
        variants = ("rotate-90", "rotate-180", "rotate-270", "roll-10", "roll-minus10", "roll-20",
                    "roll-minus20", "roll-30", "roll-minus30", "mirror", "dark", "side-light",
                    "low-contrast", "noise", "blur", "jpeg")
        samples += [replace(sample, variant=variant, condition="synthetic-" + variant)
                    for sample in samples if sample.role != "enroll" for variant in variants]
    fingerprint = sha256(args.manifest.read_bytes())
    for sample in all_samples:
        fingerprint.update(sha256(sample.path.read_bytes()).digest())
    manifest_hash = fingerprint.hexdigest()
    calibration = json.loads(args.calibration.read_text(encoding="utf-8")) if args.calibration else None
    if calibration and (calibration["partition"] != "validation" or calibration["manifest_sha256"] != manifest_hash
                        or calibration["synthetic_stress"] != args.stress
                        or calibration["max_side"] != args.max_side
                        or calibration["threshold"] != args.threshold or calibration["margin"] != args.margin
                        or calibration["target_far"] != args.target_far):
        parser.error("Calibration must use the same manifest and target FAR, validation partition only")
    from backend.app.services.face_templates import build_preprocessing_options
    from ai_pipeline.detection import FaceDetectionOptions
    from backend.app.config import get_settings

    settings = get_settings()
    base = build_preprocessing_options(settings)
    detection = FaceDetectionOptions(backend=settings.face_detection_backend, model_path=settings.face_detection_model_path,
                                    score_threshold=settings.face_detection_score_threshold, max_side=settings.face_detection_max_side)
    report = {"partition": args.partition, "manifest_sha256": manifest_hash,
              "synthetic_stress": args.stress,
              "max_side": args.max_side,
              "threshold": args.threshold, "margin": args.margin, "target_far": args.target_far,
              "notes": ["FMR/FNMR/TAR are conditional on successful extraction; rejection rate includes failures.",
                        "FPIR is transaction-level on unknown probes; matching uses fixed threshold and margin.",
                        "Latency includes decode/extraction, excludes file I/O/network; no accuracy claim from synthetic smoke data."],
              "profiles": {}}
    for name in args.profiles:
        options = profile_options(name, base)
        recognizer = FaceRecognizer(preprocessing=options, detection=detection)
        if recognizer.distance_metric != "euclidean":
            parser.error("Benchmark requires the dlib 128D model; histogram fallback cannot validate Face ID")
        if name in {"retinex", "tan-triggs"}:
            experimental_analysis(recognizer, name)
            recognizer.model_version += ":experimental-" + name
        previous = calibration["profiles"].get(name) if calibration else None
        if calibration and previous is None:
            parser.error("Every test profile must have matching validation calibration")
        if previous and previous["model_version"] != recognizer.model_version:
            parser.error("Calibration profile differs from the running configuration")
        # Warm model/detector once outside the latency samples.
        recognizer.extract_single_embedding(sample_bytes(samples[0], args.max_side))
        result = evaluate_profile(samples, recognizer, threshold=args.threshold, margin=args.margin,
                                  target_far=args.target_far,
                                  max_side=args.max_side,
                                  calibrated_threshold=previous["threshold_at_target_far"] if previous else None)
        result["preprocessing_parameters"] = vars(options)
        report["profiles"][name] = result
        print(f"{name}: correct={result['correct_identification']}/{result['known_probes']}, "
              f"FPIR={result['fpir']}, p95={result['latency_p95_ms']:.1f}ms", flush=True)
    report["protocol_warnings"] = []
    if len({s.subject for s in samples}) < 30:
        report["protocol_warnings"].append("Fewer than 30 identities: engineering smoke test, insufficient acceptance evidence")
    if len({s.session for s in samples}) < 3:
        report["protocol_warnings"].append("Fewer than three sessions")
    if args.partition == "test" and not calibration:
        report["protocol_warnings"].append("No validation calibration: test TAR@FAR is intentionally omitted")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
