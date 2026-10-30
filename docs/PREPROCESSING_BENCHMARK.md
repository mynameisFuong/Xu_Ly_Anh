# Vận hành tiền xử lý v2/v3 và benchmark recognition

## Đã triển khai

- [preprocessing.py](../ai_pipeline/preprocessing.py): decoder áp EXIF một lần,
  ma trận nguồn ↔ ảnh xử lý, similarity căn mắt tùy chọn render từ pixel gốc,
  ROI có vùng đệm, gamma LUT giới hạn 0,65–1,4 hoặc CLAHE trên luminance.
- [quality.py](../ai_pipeline/quality.py): brightness, percentile contrast,
  Laplacian, Tenengrad, tỷ lệ vùng cháy/đen, MAD ước lượng nhiễu và nhiễu xung.
  Chất lượng được đo trên đa giác pixel gốc, không tính nền canvas sau xoay.
- [analysis.py](../ai_pipeline/analysis.py): v1 không đổi; v2 có giới hạn số lần
  detector, từ chối mặt bị cắt, chọn nhánh theo chất lượng, fallback về ảnh đã
  qua quality khi enhancement/encoding lỗi. Không nới ngưỡng nhận diện.
- [experiments.py](../ai_pipeline/experiments.py): luminance MSR Retinex và
  Tan–Triggs chỉ cho benchmark. Không thay RGB runtime bằng ảnh biên/grayscale.
- [benchmark_preprocessing.py](../scripts/benchmark_preprocessing.py): so sánh
  cấu hình độc lập, không lưu ảnh/embedding trong report và không thay DB.
- [check_preprocessing_rollout.py](../scripts/check_preprocessing_rollout.py):
  thống kê số bộ năm góc tương thích, không ghi DB hay sửa môi trường.
- [preview_preprocessing.py](../scripts/preview_preprocessing.py): xuất ảnh nguồn,
  ảnh sau hình học, ảnh sau tăng cường và ảnh chẩn đoán Kirsch/Retinex/Tan–Triggs
  để quan sát. Không ghi điểm danh hoặc thay ảnh đầu vào của dlib bằng ảnh biên.

V3 là profile hiện hành kế thừa v2: giữ nguyên ảnh tốt, làm mềm đường biên ROI
khi có xử lý sáng/nhiễu, chỉ thử cứu ảnh tối vừa phải (độ sáng nguồn ≥30, đủ
tương phản/độ nét) và kiểm tra lại sau xử lý. Trong luồng nhiều mặt, v3 thử thêm
tối đa hai hướng roll ngay cả khi đã thấy mặt khác; gộp các khung về tọa độ
ảnh gốc trước khi nhận diện. Với ảnh tối không thấy mặt, v3 thử thêm một lần
gamma chỉ cho detector; ảnh đưa vào model vẫn qua kiểm tra trên nguồn gốc.
Chi phí detector và khả năng gộp nhầm cần đo bằng
camera thực. Cấu hình mặc định hiện tại là `enforce`/v3; vector v1/v2 không
được dùng trong gallery v3.

V2 mặc định không căn mắt ngoài vì [dlib tự tạo chip 150×150 có padding](https://github.com/davisking/dlib/blob/master/tools/python/src/face_recognition.cpp).
[CLAHE](https://docs.opencv.org/4.x/d5/daf/tutorial_py_histogram_equalization.html)
chỉ là một nhánh tăng tương phản; không giả định nó luôn cải thiện ResNet.

## Cấu hình hiện hành và chế độ đối chiếu

Trên máy mới, `.env.example` chọn v3 cho cả đăng ký và điểm danh:

```dotenv
PREPROCESSING_MODE=enforce
PREPROCESSING_VERSION=v3
PREPROCESSING_SHADOW_V2=false
PREPROCESSING_V2_ALIGN_EYES=false
PREPROCESSING_LIGHTING_METHOD=adaptive
PREPROCESSING_DENOISE_METHOD=off
PREPROCESSING_MAX_DETECTION_ATTEMPTS=8
```

Khi cần thí nghiệm đối chiếu v1, có thể chọn `PREPROCESSING_VERSION=v1`, bật
`PREPROCESSING_SHADOW_V2=true` và đặt
`PREPROCESSING_SHADOW_CANDIDATE_VERSION=v3`. Khi ấy v1 quyết định điểm danh,
v3 chỉ được đo trên mẫu frame theo `PREPROCESSING_SHADOW_SAMPLE_RATE`; cần mẫu
đăng ký v1 tương ứng. Đối chiếu chạy đồng bộ và tăng latency. Mode `shadow`
giữ đường legacy chưa tiền xử lý làm đối chứng. Status ở
`/face-analysis/status` có profile hiện tại/candidate và thống kê tổng hợp.

Khởi động lại backend để đọc cấu hình mới:

```powershell
.\.venv313\Scripts\python.exe scripts/run_web.py --reload
.\.venv313\Scripts\python.exe scripts/check_preprocessing_rollout.py --version v3
```

Ngày 31/10/2026, cơ sở dữ liệu thử local được chuyển sang v3: hai bộ năm góc
được tính lại từ ảnh chân dung 400×600 còn lưu, không đổi nhãn vector v1. Ảnh
đã cắt không tương đương frame gốc; đây chỉ là dữ liệu demo và nên đăng ký lại
từ camera nếu cần đánh giá độ chính xác thực tế. Cơ sở dữ liệu và ảnh này không
được đưa vào Git; máy mới chạy seed chỉ có metadata và phải đăng ký khuôn mặt.

Đoạn trên ghi lại một lần xử lý dữ liệu demo cũ, không phải migration tự động
trên mọi máy. Hồ sơ người dùng đăng ký lại sau đó có bộ mẫu riêng; lấy trạng thái
hiện tại từ API/CLI inventory, không suy ra số bộ mẫu từ mô tả lịch sử này.

## Dữ liệu benchmark

Xem trực tiếp một ảnh được phép sử dụng (đầu ra là ảnh khuôn mặt, nên lưu trong
`storage/` và không đưa lên Git):

```powershell
.\.venv313\Scripts\python.exe scripts/preview_preprocessing.py storage/recognition-benchmark/images/example.jpg storage/recognition-benchmark/preview --version v3 --lighting adaptive --denoise adaptive
```

Thêm `--align-eyes` để khảo sát căn mắt ngoài; cần cài dlib và landmark tin cậy.
Ảnh xem trước là một nhánh minh họa, không phải quyết định nhận diện. File
`metadata.json` ghi chất lượng ảnh nguồn, phép đã áp dụng và cấu hình; Retinex,
Tan–Triggs, Kirsch chỉ là ảnh thí nghiệm. Muốn kết luận có ích cho model phải
chạy benchmark với dữ liệu và ngưỡng cố định.

Dùng ảnh có quyền sử dụng. Với bài tập lớn có thể bắt đầu 5–10 người theo
[quy trình thực nghiệm](THU_NGHIEM_DO_AN.md), công bố rõ mẫu nhỏ. Khoảng 30 người
và ít nhất ba phiên/camera là mục tiêu mở rộng, không là điều kiện mới để chạy demo.
Tạo `storage/recognition-benchmark/manifest.json`; đường dẫn ảnh tính tương đối
với manifest. Ví dụ cấu trúc (thay ảnh và danh tính bằng dữ liệu thật):

```json
{
  "samples": [
    {"path": "images/v01_day1.jpg", "subject": "v01", "session": "day1", "role": "enroll", "partition": "validation"},
    {"path": "images/v01_day2.jpg", "subject": "v01", "session": "day2", "role": "probe", "partition": "validation", "condition": "side-light"},
    {"path": "images/v_unknown.jpg", "subject": "v_unknown", "session": "day3", "role": "unknown", "partition": "validation"},
    {"path": "images/t01_day1.jpg", "subject": "t01", "session": "day1", "role": "enroll", "partition": "test"},
    {"path": "images/t01_day3.jpg", "subject": "t01", "session": "day3", "role": "probe", "partition": "test"},
    {"path": "images/t_unknown.jpg", "subject": "t_unknown", "session": "day3", "role": "unknown", "partition": "test"}
  ]
}
```

Một người có thể có nhiều ảnh enroll/góc, nhưng probe phải khác phiên. Tập
validation/test phải khác người. Unknown không có ảnh enroll trong tập đó.
Với ảnh tổng hợp tạo ngoài tool, khai báo `source_id` chung cho mọi biến thể
cùng ảnh; tool kiểm tra cả source_id và SHA-256 nội dung để chặn rò rỉ.
Tool không thể tự xác minh hai mã người/phiên khác nhau có đúng thực tế hay không.

## Chạy ablation

```powershell
.\.venv313\Scripts\python.exe scripts/benchmark_preprocessing.py storage/recognition-benchmark/manifest.json --partition validation --profiles legacy v1 v2-geometry v2-adaptive v2-denoise v2-align v3-geometry v3-adaptive v3-denoise v3-align --output storage/recognition-benchmark/validation.json
.\.venv313\Scripts\python.exe scripts/benchmark_preprocessing.py storage/recognition-benchmark/manifest.json --partition test --profiles legacy v1 v2-geometry v2-adaptive v2-denoise v2-align v3-geometry v3-adaptive v3-denoise v3-align --calibration storage/recognition-benchmark/validation.json --output storage/recognition-benchmark/test.json
```

Giữ cố định threshold/margin; mặc định 0,52/0,04. Khi benchmark cấu hình khác,
ghi rõ `--threshold`/`--margin`. TAR@FAR trên test chỉ dùng cutoff từ validation
cùng manifest+nội dung ảnh, target FAR và profile; không tự chọn cutoff từ test.
Có thể chạy riêng `--profiles retinex tan-triggs` cho thí nghiệm P3. Những nhánh
này giữ quality gate trên ảnh nguồn, chỉ đổi xử lý ROI sau kiểm tra.

`--stress` tạo thêm probe xoay 90/180/270, roll ±10/±20/±30, lật gương, tối,
ánh sáng lệch bên, tương phản thấp, nhiễu, mờ và JPEG; ảnh enroll không bị
thay đổi, mọi biến thể ở cùng partition/session. Chỉ coi đây là kiểm tra kỹ
thuật; phải kiểm tra bằng camera thật. Không suy luận mirror từ mắt.
`--max-side 640` đưa cùng một resize về cạnh dài tối đa 640 px vào trước mọi
profile để mô phỏng kích thước webcam; mặc định 0 giữ độ phân giải gốc.
Report ghi rõ giá trị này và calibration/test phải dùng giống nhau. Thời gian
tạo biến thể/resize chung nằm ngoài số đo extraction.

Report phân biệt:

- FMR/FNMR và TAR@FAR: so sánh cặp sau khi trích xuất thành công.
- `false_reject_rate`: probe người đã đăng ký không nhận đúng, gồm lỗi trích
  xuất, thiếu mẫu, từ chối và nhận sai; `misidentified_known` đếm nhận sai người.
- FPIR: unknown bị nhận thành người trong gallery / toàn bộ unknown probe,
  gồm cả unknown bị từ chối chất lượng ở mẫu số.
- `known_failure_subject_bootstrap`: macro failure rate và CI bootstrap theo
  người; không coi các frame/biến thể cùng người là độc lập.
- p50/p95: decode + detect + quality + encode, sau một warmup, không gồm I/O
  file/network. Đo camera end-to-end riêng để kiểm tra ngân sách ≤30 ms thêm
  preprocessing và ≤10% p95 tổng; chưa cam kết đạt hai mục tiêu này.
- `preprocessing_p95_ms`: thời gian orientation/warp, đo quality và enhancement
  ở v2, không gồm detector, landmarks, decode hay encode. Số này có ở v2;
  legacy/v1 trả null vì không chèn timer làm thay đổi nhánh đối chứng.

Nếu dữ liệu quá ít, report cảnh báo thiếu bằng chứng nghiệm thu. Cutoff có FAR
thực nghiệm bằng 0 trên vài chục so sánh không chứng minh FAR thấp trong thực tế.

## Chuyển profile và rollback

1. Đo baseline và chọn cấu hình trên validation; đóng băng trước khi chạy test.
2. Đặt v2 enforce trên môi trường thử nghiệm/tập lớp mới. Thu năm góc từ ảnh
   nguồn hoặc camera hợp lệ, cùng thông số sẽ dùng khi quét. Môi trường hiện tại
   không có chức năng tự chuyển mẫu v1 sang v2.
3. Kiểm tra inventory và accuracy/độ trễ trước khi chuyển cấu hình hệ thống chính.
   Nếu có dữ liệu cũ cần giữ, sao lưu DB và ảnh theo quy trình vận hành trước khi
   reset enrollment; endpoint reset có thể xóa bộ mẫu của người đó.
4. Chuyển `PREPROCESSING_VERSION=v2`, mode=enforce, khởi động lại cả backend và
   worker. Enrollment/scan dùng chung adapter cấu hình và model_version.
5. Rollback cấu hình/profile và dữ liệu mẫu đi cùng. Không chỉ đổi pipeline
   trong khi gallery chứa duy nhất vector của profile khác.

Không tự thêm undistort khi chưa có intrinsics camera đo được; không warp 2D để
bịa phần mặt bị che khi yaw/pitch lớn. Các lựa chọn cache/tracker/chọn frame
chỉ được bật thêm sau benchmark thực; hiện giữ xác nhận bằng embedding mới.

## Kết quả kiểm tra kỹ thuật ngày 30/10/2026

- 101 kiểm thử Python/backend và 5 kiểm thử giao diện Chrome đạt; Ruff và kiểm
  tra cú pháp JavaScript đạt. Một lần chạy tổng thể trước đó có một test Chrome
  hết thời gian chờ camera giả lập; test được sửa để đợi camera thực sự sẵn sàng
  và nhóm giao diện đã chạy lại thành công.
- Đã chạy dlib thật trên ảnh ví dụ công khai của
  [face_recognition](https://github.com/ageitgey/face_recognition/tree/master/examples),
  resize cạnh dài 640 px, gồm một ảnh đăng ký, bốn probe cùng người (gốc, xoay,
  tối, ít tương phản) và một probe người khác. Mười cấu hình đều chạy xong;
  v1 và các biến thể v2 nhận đúng cả bốn probe cùng người trong phép thử này.
  Đây chỉ là smoke test hai người, không chứng minh accuracy hoặc FAR thực tế.
- Trong mẫu nhỏ đó, p95 tổng cho v2 adaptive khoảng 1.423 ms và p95 phần
  preprocessing khoảng 8,2 ms; Retinex thử nghiệm khoảng 78,7 ms cho riêng phần
  preprocessing. Những con số ít mẫu này không phải kết quả nghiệm thu SLA;
  cần đo lại trên camera, người và tải thực tế. Report JSON local nằm tại
  `storage/preprocessing-smoke/report-640.json` và không được đưa vào Git.
- Đối chiếu trực tiếp với cùng một ảnh dlib: khi v1 enforce + v2 shadow,
  embedding v1 128 chiều được trả về giống hệt embedding v1 không shadow;
  nhánh v2 cũng trích xuất thành công. Điều này kiểm tra hợp đồng trên ảnh thử,
  không chứng minh các profile có thể dùng chung template.

## Kiểm tra kỹ thuật v3 ngày 31/10/2026

Chạy benchmark trên tập ảnh ví dụ công khai local gồm một người đăng ký, bốn
probe cùng người (ba biến thể tổng hợp) và một probe người lạ, cùng cạnh dài
640 px. `legacy` nhận đúng 3/4; `v1`, `v2-adaptive` và bốn profile v3 thử đều
nhận đúng 4/4; người lạ không bị nhận nhầm trong mẫu này. P95 tổng ở lần chạy
đơn lẻ là khoảng 1,39 giây cho `v2-adaptive`, 1,91 giây cho `v3-adaptive` và
2,16 giây cho `v3-denoise`; phần tiền xử lý được đo lần lượt khoảng 6,5, 8,2
và 10,3 ms. Bảng đầy đủ nằm local tại `storage/preprocessing-smoke/v3-comparison.json`.
Những số ít mẫu này **không** đủ để tuyên bố v3 tốt hơn hoặc kém hơn về độ
chính xác/tốc độ; có thể bị ảnh hưởng bởi warmup và tải CPU. V3 hiện đã được
bật để demo, còn lợi ích thực tế cần đo thêm trên camera và người tham gia.
Một kiểm tra riêng trên ảnh ví dụ đó giảm cường độ pixel xuống 30%: v2 từ chối
vì độ sáng mặt 43,6, v3 chấp nhận sau gamma và biên ROI; hai embedding v3 từ
ảnh gốc và ảnh tối cách nhau 0,215 theo Euclidean. Đây là một ảnh và một biến
thể tổng hợp, không chứng minh độ chính xác trên ảnh chụp thiếu sáng thật.
