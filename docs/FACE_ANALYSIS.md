# Tiền xử lý ảnh và chống giả mạo

## Trạng thái và giới hạn

Pipeline hỗ trợ `off`, `shadow`, `enforce` độc lập cho tiền xử lý và liveness.
Giữ mặc định cấu hình nền là `off` để không tự đổi profile embedding; **web mới
mặc định yêu cầu liveness**, nên từ chối điểm danh tự động khi PAD chưa sẵn sàng.
Có hai backend: `hog-svm` tự huấn luyện và `minifasnet` pretrained qua ONNX CPU.
Trọng số tải riêng vào storage, không nằm trong git. Test tổng hợp kiểm tra chính
sách chặn, không chứng minh độ chính xác chống ảnh in/video.

## Bật liveness web trên Windows (Python 3.13 x64)

Trong môi trường đã cài engine Face ID theo README:

```powershell
python -m pip install -r requirements-liveness.txt
python scripts/download_liveness_models.py
```

Đặt trong `.env` cho **thử nghiệm local**:

```dotenv
PREPROCESSING_MODE=enforce
PREPROCESSING_SEARCH_ROLLS=true
LIVENESS_MODE=enforce
LIVENESS_BACKEND=minifasnet
LIVENESS_MODEL_DIR=./storage/pad-models/minifasnet-v1
LIVENESS_LIVE_THRESHOLD=0.90
LIVENESS_ALLOW_PRETRAINED=true
WEB_LIVENESS_REQUIRED=true
```

`LIVENESS_ALLOW_PRETRAINED=true` chỉ cho dùng các trọng số MiniFASNet đã ghim
checksum trong nghiên cứu local; manifest vẫn có `approved_for_enforcement=false`.
Không áp dụng ngoại lệ này cho HOG/SVM tự huấn luyện. Deployment đã được đánh giá
cần đặt allow_pretrained=false và duyệt model sau khi xem báo cáo thực địa.
Ngưỡng 0.90 là điểm xuất phát bảo thủ, không phải xác suất chống gian lận đã hiệu chuẩn.

Khởi động lại backend. Kiểm tra `/face-analysis/status`: `web_liveness_ready=true`,
`liveness_backend=minifasnet`. Nếu vừa bật/đổi tiền xử lý, thu lại đủ 5 góc cho profile
mới trước khi điểm danh. Dữ liệu cũ không bị tự xóa hoặc đổi model_version.

Nếu `.env` đã enforce nhưng status vẫn off, terminal IDE có thể giữ biến cũ. Dừng
backend rồi chạy `python scripts/run_web.py --reload` (hoặc `make run`) để launcher
local đọc lại `.env` và đặt đúng thư mục dự án. Tải lại trang sau khi server sẵn sàng;
panel sẽ hiển thị `web_liveness_message` từ backend nếu có lỗi cấu hình/model.

## Bắt lại khuôn mặt khi quay đầu

HOG dễ bỏ sót mặt ở góc yaw/pitch; xoay ảnh chỉ hỗ trợ roll. Chế độ hybrid dùng
thêm [YuNet của OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet)
qua OpenCV DNN CPU, không đổi dlib ResNet hoặc ngưỡng danh tính/PAD.

```powershell
python scripts/download_face_detector.py
```

```dotenv
FACE_DETECTION_BACKEND=hybrid
FACE_DETECTION_MODEL_PATH=./storage/face-models/face_detection_yunet_2023mar.onnx
FACE_DETECTION_SCORE_THRESHOLD=0.90
FACE_DETECTION_MAX_SIDE=640
```

Artifact 232589 byte, SHA-256
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`, được ghim
commit và kèm giấy phép MIT upstream khi tải. Không tải tự động trong request.
Thiếu/sai artifact thì hỗ trợ YuNet không sẵn sàng, HOG vẫn hoạt động; status
`face_detection` trả readiness/lỗi tổng quát và số frame cứu được, không trả path.

HOG tiếp tục chạy trên ảnh gốc; YuNet chạy trên bản giới hạn cạnh dài 640 pixel,
map box về kích thước nguồn trước khi đo chất lượng/PAD. Giữ box HOG khi hai
detector cùng thấy một mặt; nếu YuNet thấy thêm mặt khác thì từ chối nhiều người.
Nếu cả hai chưa thấy mặt, thử CLAHE chỉ ở nhánh phát hiện. Landmarks, căn mắt và
embedding vẫn lấy ảnh theo quy trình cũ, PAD luôn nhận pixel nguồn. Tìm roll
±20/±40 trước xoay 90/180/270; canvas xoay dùng YuNet nếu sẵn sàng để tránh chạy
HOG nhiều lần. Không dùng tracking hoặc dựng mặt chính diện để thay bằng chứng.

Chỉ bật detector hỗ trợ không đổi profile embedding, không tự tái gắn nhãn mẫu.
Nhánh HOG hiện hữu giữ nguyên box; cần đánh giá khoảng cách/nhận nhầm của các
góc mới được cứu trên dữ liệu thực địa. Đổi mirror/căn mắt/CLAHE vẫn theo quy
tắc profile và thu lại 5 góc như trước.

Web cho bắt lại khi tạm mất mặt, ảnh nhỏ/tối/chói/nhòe hoặc encode thất bại.
Frame lỗi vẫn kiểm nonce/sequence/hash, không tăng bước, không cập nhật anchor,
không công bố danh tính hay ghi DB. Thời gian giữ bước hiện tại bị reset; các bước
đã hoàn thành được giữ. Max-gap 5 giây tính từ frame hợp lệ gần nhất (hoặc lúc
tạo thử thách), retry không gia hạn gap hoặc TTL. Spoof/uncertain, nhiều mặt,
đổi danh tính, replay và sai protocol vẫn hủy. Quay nhẹ theo góc server hướng dẫn
và giữ yên khi thông báo đúng góc; không cần quay mặt sang bên hoàn toàn.

## Các lớp kiểm tra web

1. Chỉ một mặt, đạt chất lượng nguồn; tìm roll ±20/±40 rồi hướng 90/180/270 khi
   detector chưa thấy mặt. Ước lượng pose trước căn mắt, CLAHE ở nhánh embedding.
2. MiniFASNetV2 và V1SE dùng crop nguồn 2.7/4.0 theo thuật toán dịch biên upstream,
   BGR float32 0..255, NCHW 1×3×80×80; softmax lớp 1 là live. Lấy **min** hai điểm,
   cả hai phải đạt ngưỡng, không dùng điểm trung bình che một mô hình từ chối.
3. Server tạo thử thách `center → hướng ngẫu nhiên → center` ba lần. Chỉ công bố
   hướng hiện tại. Mỗi bước cần tối thiểu 2 frame mới, giữ tư thế ít nhất 0.5 giây.
4. Mỗi frame phải khớp cùng sinh viên và embedding gần anchor ban đầu; nonce bước,
   thứ tự và hash ảnh được server kiểm tra. Khoảng cách request tối thiểu 0.25 giây,
   mất luồng quá 5 giây hoặc hết 45 giây thì bắt đầu lại. Client không cung cấp pose,
   kết luận live hoặc timestamp để quyết định pass.
5. Chỉ frame cuối pass mới được ghi điểm danh. Thử thách được tiêu thụ nguyên tử,
   không đổi thành token dùng lại cho người khác hoặc những lượt điểm danh sau.
   Pending/failed không trả danh tính, không lưu ảnh minh chứng hay sự kiện.

UI hiển thị hướng dẫn và tiến độ riêng; viền xanh/tên chỉ xuất hiện sau khi API
đã ghi thành công. Desktop đã được cập nhật giao thức tương tự; camera worker
dùng token tin cậy vẫn qua PAD và xác nhận nhiều frame trên server khi enforce.

Store giữ tối đa 128 thử thách trong RAM, 256 hash/frame mỗi thử thách, không giữ
ảnh. Anchor embedding chỉ tồn tại tới hết hạn/consume/reset. Mở thử thách mới với
cùng user/session hủy thử thách trước; nhiều tab cùng user/session sẽ phải quét lại.
Restart backend làm mất thử thách, client tự bắt đầu lại. Chạy **một process** cho
MVP; khi scale nhiều process cần shared store và consume nguyên tử (Redis/DB),
không dựa vào sticky routing như một bảo đảm an ninh.

Đăng ký 5 góc/import cũng bắt buộc PAD khi enforce, nhưng vẫn là thao tác quản trị
có giám sát, không phải chứng nhận hiện diện từ thử thách web. Không tự động import
ảnh tĩnh thành người đã có mặt.

Nguồn: [MiniFASNet upstream](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing),
[ONNX exports](https://github.com/yakhyo/face-anti-spoofing/releases/tag/weights),
[giấy phép upstream Apache-2.0](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/blob/master/LICENSE).
Không phân phối lại trọng số trong repo; trước phân phối thương mại cần kiểm tra
điều khoản trọng số/dataset với bên phát hành. Code crop/inference được triển khai
theo hợp đồng upstream và ghi nguồn, không tải/chạy Python từ bên thứ ba.

### Đánh giá MiniFASNet trên camera mục tiêu

CSV dùng cùng định dạng/tách người như phần HOG/SVM bên dưới. Chạy với dữ liệu được
phép sử dụng, đủ live/print/replay trong mỗi split:

```powershell
python scripts/evaluate_liveness.py --dataset storage/pad-data/dataset.csv --output storage/pad-reports/run-01.json
```

Báo cáo ghi counts, APCER riêng print/replay, BPCER, số frame lỗi nguồn/unavailable
và p50/p95. Mẫu live lỗi nguồn vẫn tính vào BPCER; không bỏ các mẫu khó để làm đẹp
điểm. Đây chỉ là đánh giá PAD, chưa đo toàn bộ thử thách/web/nhận diện. Điều chỉnh
ngưỡng bằng validation, đóng băng rồi đo test chưa thấy; không lặp tune trên test.
Test luồng web riêng bằng ảnh in (phẳng/uốn/đục mắt), điện thoại/tablet/LCD phát
video (nhiều độ sáng/tần số), webcam/ánh sáng/kính chưa thấy, đổi người giữa chừng,
mất mạng, replay request và client sửa camera_id. Ghi cả phiên bị chặn và người
thật bị từ chối. Chưa có dataset thực địa trong repository nên chưa có số liệu này.

HOG + SVM và DFT không thể bảo đảm phát hiện mọi video phát lại. Cần đánh giá với
camera, máy in, màn hình, JPEG, ánh sáng và đối tượng thực tế trước khi vận hành.
PAD ảnh RGB xử lý presentation attacks; không xác thực phần cứng camera và không
chống được mọi trường hợp client chèn trực tiếp dữ liệu ảnh số.

## Luồng và hợp đồng

Các thành phần:

- [preprocessing.py](../ai_pipeline/preprocessing.py): ảnh BGR `uint8 H×W×3`, unmirror
  theo cấu hình nguồn, xoay 90/180/270 độ không nội suy, căn roll theo hai mắt,
  CLAHE trên độ sáng, Kirsch tùy chọn ở nhánh phân tích độc lập.
- [liveness.py](../ai_pipeline/liveness.py): crop nguồn có ngữ cảnh, HOG và phổ DFT
  2D, chuẩn hóa đặc trưng và SVM tuyến tính. Điểm trả về là **margin**, không phải xác suất.
- [analysis.py](../ai_pipeline/analysis.py): điều phối, fallback và chỉ số tổng hợp.
- [recognition.py](../ai_pipeline/recognition.py): adapter giữ các phương thức public,
  vector float32 128 chiều của dlib hoặc histogram 256 chiều của fallback.

Thứ tự enforce:

1. Giải mã bằng OpenCV với hành vi orientation của decoder hiện tại; không áp dụng
   thêm EXIF lần hai. Chỉ thử xoay hình học khi cấu hình tiền xử lý cho phép.
2. Phát hiện đúng một mặt; nhiều mặt bị từ chối, không chọn mặt lớn nhất để nhận diện.
3. Đo kích thước, độ sáng và độ mờ trên crop nguồn trước resize/tăng cường.
4. PAD trên pixel nguồn chưa CLAHE/Kirsch/căn mắt. Nếu không live, dừng trước
   landmarks và embedding trong chế độ liveness enforce.
5. Landmarks và yaw/pitch trên ảnh đã định hướng, trước căn roll. Không dùng affine
   để giả lập mặt chính diện từ yaw/pitch lớn. Pose không ước lượng được không được
   giả thành góc front.
6. Căn mắt và CLAHE cho nhánh nhận diện; dlib tiếp tục dùng cơ chế descriptor của nó.
7. So khớp template cùng profile, xác nhận nhiều frame ở camera worker nâng cấp,
   sau đó mới ghi điểm danh/minh chứng.

`face_box` vẫn là `(x, y, width, height)` trong ảnh đầu vào đã giải mã, không phải
tọa độ crop hoặc tọa độ ảnh đã xoay. Ma trận biến đổi ánh xạ ngược cả bốn góc;
crop được clip để không dùng chỉ số NumPy âm. Hàm tiền xử lý không sửa mảng đầu vào.
Nếu căn mắt làm cắt vùng mặt hoặc landmarks không tin cậy, dùng ảnh chưa căn.
Nếu mã hóa sau tăng cường không thành công, có thể thử lại ảnh chưa tăng cường;
không bỏ qua một gate PAD đã thất bại.

Video selfie trên web chỉ mirror ở CSS. Canvas gửi pixel không mirror, vì vậy
`PREPROCESSING_MIRROR_INPUT=false` là mặc định đúng. Chỉ bật khi mọi ảnh đầu vào
của deployment đó đã được xác định là mirror thực sự. Không suy mirror từ hai mắt.
Kirsch là hàm phụ để nghiên cứu/kiểm tra cạnh, không thay thế ảnh màu của dlib/PAD.

## Cấu hình và triển khai

Xem [.env.example](../.env.example). Để thử nghiệm không thay quyết định:

```dotenv
PREPROCESSING_MODE=shadow
LIVENESS_MODE=shadow
LIVENESS_MODEL_DIR=./storage/pad-models/experiment-01
```

Không đặt `LIVENESS_MODEL_DIR` nếu chưa có model; shadow sẽ đếm trạng thái unavailable,
đường nhận diện cũ vẫn hoạt động. Kết quả tiền xử lý shadow không được lưu thành template.

Khi `PREPROCESSING_MODE=enforce`, model_version có suffix `pre-v1-...` theo cấu hình.
Không trộn embedding đã tăng cường với template legacy chưa được đánh giá tương thích.
Wizard cần thu đủ năm góc **cùng model_version**. Template cũ không bị xóa; để rollback,
đặt mode về off và khởi động lại. Muốn dùng profile mới phải đăng ký lại có kiểm soát.
Ảnh chân dung cũ 400×600 là bản crop/resize, không nên tự dùng để tái tạo template gốc.

Model/recognizer được nạp một lần mỗi process và khóa khi dùng chung giữa request.
**Khởi động lại backend và worker sau mỗi lần đổi cấu hình hoặc artifact.** Không
ghi đè model đang chạy. Backend chỉ cần OpenCV/NumPy khi sử dụng các chức năng ảnh;
các API nghiệp vụ khác không tự nạp model PAD.

### API và camera worker

- `POST /sessions/{id}/liveness-challenge`: user/teacher/admin, tạo bước đầu.
- `POST /sessions/{id}/scan-frame`: web/desktop, bổ sung `challenge_id`, `step_token`,
  `sequence`; response bổ sung `liveness`. Bỏ các trường mới khi web guard bật sẽ
  chỉ nhận `required`, không thể ghi điểm danh. Không chọn policy theo camera_id.
- `POST /sessions/{id}/camera-scan-frame`: camera token, cùng pipeline server;
  thêm query tùy chọn `dry_run=true`, `stream_id=<ID mới cho mỗi lần mở camera>`.
- `GET /face-analysis/status`: tài khoản được phép sử dụng hệ thống.
- `GET /camera/pipeline`: camera token; worker đọc policy từ backend khi khởi động.

Status gồm mode, version, readiness, approval và counters/latency tổng hợp. Không trả
ảnh, embedding, danh tính, đường dẫn model hoặc dữ liệu từng frame trong metrics.
Latency p50/p95 là cửa sổ tối đa 128 quan sát trong process, không phải benchmark
độ chính xác hay SLA. Shadow distance chỉ hỗ trợ đánh giá độ lệch embedding,
không tự chứng minh tương thích danh tính.

Worker gửi ảnh lên backend khi một trong hai mode khác off; không cần model PAD
trên máy camera. Khi cả hai off, worker tiếp tục nhận diện cục bộ. Backend ở chế độ
enforce **từ chối sự kiện recognized tự khai** qua `/recognition-events`, kể cả
payload có trường liveness tự thêm. Cần cập nhật worker trước khi bật enforce.
Worker không chuyển về gửi sự kiện chưa xác minh khi server phân tích lỗi.

Camera endpoint xác nhận mặc định ba hit trong bốn giây, tách theo session/camera/
stream. Mất mặt, bị PAD từ chối, đổi người hoặc quá hạn sẽ reset. Store giới hạn
128 stream mỗi process; khi đầy sẽ loại stream cũ nhất. Web/desktop dùng thử thách
mới nêu trên. Nếu chạy nhiều backend worker, cần sticky routing hoặc chuyển store
này sang kho dùng chung trước khi yêu cầu xác nhận liên tục đáng tin cậy.

`dry_run` chạy phân tích và bộ đếm xác nhận tạm thời nhưng không tạo sự kiện,
điểm danh hay ảnh minh chứng. Liveness fail trả response bình thường với decision
unknown, không danh tính; enrollment trả accepted=false và không tăng tiến độ.
Chế độ enforce thiếu/hỏng/chưa duyệt model (và không bật ngoại lệ pretrained
MiniFASNet nghiên cứu) sẽ từ chối tự động; có thể chụp lại
hoặc dùng quy trình điểm danh thủ công có phân quyền/audit hiện tại.

Upload/import ảnh tĩnh cũng đi qua pipeline cấu hình. Chúng không chứng minh
người đó đang hiện diện; import không có pose vẫn là ảnh tham chiếu và không tự
hoàn tất enrollment năm góc. Không dùng kết quả PAD tĩnh làm chứng nhận hiện diện.

## Dataset và huấn luyện

Cài dependency để chạy test HTTP và pipeline:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Cài engine Face ID theo hướng dẫn hiện có nếu cần dlib. Training không cần thêm
scikit-learn; SVM dùng OpenCV. Dataset CSV chứa **ảnh camera đầy đủ** với các cột:

| path | label | split | subject_id | session_id |
|---|---|---|---|---|
| train/person01-live.jpg | live | train | person01 | capture01 |
| validation/person02-print.jpg | print | validation | person02 | capture02 |
| test/person03-replay.jpg | replay | test | person03 | capture03 |

Bảng trên chỉ minh họa định dạng; **mỗi split** phải có đủ live, print và replay.
Đường dẫn tương đối được tính từ vị trí CSV. Tất cả ảnh của cùng người phải ở
cùng split, kể cả các frame/phiên/ảnh in/video mang danh tính người đó. Dùng ID
ẩn danh ổn định; không đổi ID để chia frame của cùng video qua nhiều split.
CLI từ chối đường dẫn/nội dung trùng, subject lặp giữa split, ảnh không giải mã
được, không đúng một mặt hoặc không đạt quality gate runtime.

```powershell
python scripts/train_liveness.py --dataset storage/pad-data/dataset.csv --output storage/pad-models/experiment-01 --target-apcer 0.05
```

Thư mục output phải mới để không ghi đè một model đang dùng. Artifacts gồm:

- `svm.xml`, `normalizer.npz`: SVM và mean/scale chỉ fit từ train.
- `manifest.json`: feature/crop version, chiều vector, hướng margin, hai ngưỡng,
  mapping nhãn, checksum và trạng thái duyệt.
- `evaluation.json`: số mẫu, APCER chung/theo print/replay và BPCER trên validation/test.

Ngưỡng live được chọn trên validation sao cho APCER của **từng loại tấn công**
không vượt mục tiêu yêu cầu. Không điều chỉnh ngưỡng bằng test. Giá trị APCER mục
tiêu là mục tiêu hiệu chuẩn, không phải bảo đảm với camera/dữ liệu chưa thấy.
Khoảng giữa spoof_threshold và live_threshold là uncertain; runtime chỉ tự động
chấp nhận khi margin đạt live_threshold. Khác nhau về nén, xoay và thiết bị phải
có trong dữ liệu đánh giá, vì resize/DFT không bảo đảm bất biến với chúng.

CLI luôn xuất `approved_for_enforcement=false`. Trước khi đổi thành true, người
chịu trách nhiệm cần xem đủ số mẫu, false accept/reject, từng loại tấn công,
thiết bị chưa thấy và tác động tới nhận diện. Việc sửa cờ approval không làm
model chính xác hơn; đây là xác nhận triển khai nội bộ. Thiếu dữ liệu hoặc kết quả
không đạt thì giữ shadow. Không dùng kết quả test vector tổng hợp để duyệt model.

Enforcement chỉ chạy model có manifest tương thích, checksum đúng và đã duyệt.
Đoạn này áp dụng cho artifact HOG/SVM tự huấn luyện; ngoại lệ MiniFASNet pretrained
đã được nêu riêng ở trên.
Không thay đổi cấu hình feature/crop trong runtime để cố khớp model khác.
Không log ảnh, embedding hoặc sao chép dữ liệu sinh trắc vào repository.

## Kiểm thử và phần còn cần xác minh thực địa

Các test mới kiểm tra round-trip tọa độ, mắt nằm ngang, giữ dtype/shape, không sửa
ảnh nguồn, raw PAD trước tăng cường, short-circuit trước landmarks/embedding,
shadow giữ kết quả legacy, checksum/model approval, giới hạn/reset temporal,
auth API, chống bypass sự kiện, dry-run không ghi DB, enrollment và profile.

Cần dùng dữ liệu được phép sử dụng để đo tiếp: APCER/BPCER theo thiết bị/điều kiện,
nhận nhầm/từ chối nhầm với template cũ/mới, roll/yaw/pitch và ảnh EXIF từ điện
thoại, thời gian p50/p95 CPU trên máy mục tiêu, camera vật lý và luồng desktop/web.
