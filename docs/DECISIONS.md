# Quyết định kỹ thuật

## Giữ kiến trúc local-first cho bản demo

Hệ thống hiện có là FastAPI + SQLAlchemy + SQLite và đã có luồng nghiệp vụ lớp học hoàn chỉnh. Thay toàn bộ bằng PostgreSQL/Redis/MinIO/Next.js ngay trong bản demo sẽ làm tăng rủi ro vận hành mà không cải thiện trải nghiệm trình diễn. Vì vậy bản này giữ modular monolith, bổ sung dashboard và console web chuyên nghiệp. Các interface nghiệp vụ vẫn tách đủ rõ để nâng cấp hạ tầng sau.

## Dữ liệu sinh trắc học

Embedding và ảnh không được ghi ra log. Truy cập ảnh đi qua endpoint có phân quyền. Production phải dùng mã hóa volume, TLS, chính sách lưu giữ/xóa dữ liệu và PostgreSQL + pgvector như đặc tả.

## Nhận diện đa góc và chống giả mạo

Enrollment ưu tiên `ageitgey/face_recognition`, mô hình dlib ResNet 128 chiều và 68 facial landmarks. OpenCV `solvePnP` ước lượng yaw/pitch để bắt buộc thu đủ chính diện, trái, phải, lên và xuống. Realtime so sánh Euclidean với toàn bộ pose template của mỗi người, sau đó kiểm tra ngưỡng và margin với người thứ hai. Engine histogram cũ chỉ là fallback tương thích và không được phép chạy wizard đa góc.

Pipeline kiểm tra một khuôn mặt, kích thước, độ sáng, độ mờ và idempotency; camera worker còn xác nhận nhiều khung hình. Web/desktop giữ chính sách xác nhận hiện tại.

Đã có adapter tiền xử lý ảnh và baseline PAD HOG + SVM kết hợp đặc trưng DFT, cấu hình off/shadow/enforce độc lập và mặc định off. Không kèm model PAD đã được huấn luyện/duyệt. Không coi test tổng hợp là nghiệm thu chống ảnh in/video phát lại; cần dữ liệu và đánh giá thực địa. MiniFASNet/ONNX vẫn là hướng có thể bổ sung sau qua cùng guard interface. Xem [thiết kế, huấn luyện và vận hành](./FACE_ANALYSIS.md).

## Liveness web nhiều lớp (29/10/2026)

Theo yêu cầu nâng cấp web, bổ sung ensemble MiniFASNetV2 (crop 2.7) và V1SE
(crop 4.0) qua ONNX Runtime CPU, đúng hướng công nghệ trong đặc tả. Giữ FastAPI,
SQLite, dlib, schema embedding và các quy tắc điểm danh của MVP hiện hành.
Mô hình chỉ nhận pixel BGR nguồn, không CLAHE/căn mắt; cả hai mô hình phải đạt
ngưỡng. Trọng số tải riêng, kiểm tra SHA-256, không commit vào git.

Web dùng thử thách quay đầu ngẫu nhiên, từng bước có nonce, thời hạn và kiểm tra
cùng danh tính. Mỗi bước cần nhiều frame mới, đủ khoảng thời gian; server tiêu thụ
thử thách một lần trước khi ghi điểm danh. Không tin kết quả liveness/pose do client
khai. Kiểm tra này bổ sung PAD, không coi chuyển động đầu là bằng chứng tuyệt đối.
API camera-token vẫn dành cho worker tin cậy và bắt buộc PAD khi enforce; không
cho gửi sự kiện recognized tự khai. Production cần thay cơ chế xác thực demo và
nguồn camera đáng tin cậy để chống chèn video số/deepfake tương tác.

HOG/SVM tự huấn luyện vẫn bắt buộc duyệt artifact. MiniFASNet pretrained cũng giữ
cờ chưa duyệt theo mặc định; môi trường nghiên cứu local có thể chủ động đặt
`LIVENESS_ALLOW_PRETRAINED=true` để thử với các trọng số đã ghim checksum, không
đồng nghĩa nghiệm thu APCER/BPCER. Không tự đặt cờ approved hoặc công bố độ chính
xác khi chưa có dữ liệu thực địa. Kế hoạch đánh giá trong FACE_ANALYSIS vẫn áp dụng.

Tiền xử lý enforce tạo profile mới như thiết kế cũ: cần thu lại năm góc cho profile
mới; không đổi nhãn hoặc tự tái sử dụng embedding legacy. Bổ sung tìm mặt nghiêng
roll khi detector chính diện thất bại; không dựng mặt chính diện từ yaw/pitch lớn.

## Cấu hình local và terminal IDE

VS Code có thể đưa giá trị .env cũ vào environment của terminal; environment được
Pydantic ưu tiên hơn file mới nên backend vẫn off dù .env đã enforce. Tắt tự inject
env-file vào terminal trong workspace và bổ sung `scripts/run_web.py`: chỉ launcher
local đọc .env hiện tại với override trước khi khởi động Uvicorn/reloader, đồng thời
đặt cwd là project root. Không đổi precedence của Settings trong triển khai thông
thường. Status/UI trả lý do readiness cụ thể thay cho thông báo chung, không lộ
secret, ảnh, embedding hoặc đường dẫn nội bộ.

## Giảm mất mặt khi quay đầu

HOG chính diện dễ bỏ sót yaw/pitch; xoay ảnh roll không sửa được hiện tượng này.
Bổ sung YuNet từ OpenCV Zoo (MIT) làm detector hỗ trợ, chạy CPU qua OpenCV DNN,
giữ dlib ResNet/68 landmarks, ngưỡng danh tính và PAD hiện hành. Nhánh HOG đã thấy
mặt vẫn giữ box cũ; YuNet bổ sung mặt bị bỏ sót và phát hiện người thứ hai. CLAHE
chỉ hỗ trợ tìm box khi ảnh gốc chưa thấy mặt, không đưa ảnh tăng cường vào PAD.
Không thay công thức embedding/profile hoặc tự chuyển dữ liệu mẫu cũ. Backend
hybrid phải được bật bằng cấu hình; artifact tải riêng, ghim commit và SHA-256.

Một frame mất mặt/nhòe không hủy các bước liveness đã hoàn thành. Server tiêu thụ
sequence/hash của frame lỗi, xóa thời gian giữ bước hiện tại và chờ bắt lại trong
giới hạn max_gap tính từ frame hợp lệ gần nhất, không gia hạn TTL. Không dùng box
tracking hoặc embedding cũ để xác nhận frame mới. Spoof, nhiều mặt, đổi người,
replay và sai nonce vẫn hủy thử thách. Cần đo lại trên webcam thực tế; test không
chứng minh tỷ lệ bỏ sót đã giảm từ mức người dùng quan sát.

## Khắc phục gián đoạn sau thử camera thực tế

Đo trực tiếp LG Camera theo yêu cầu người dùng cho thấy các frame qua PAD khớp
mẫu hiện hữu, nhưng PAD có frame uncertain và độ trễ đáng kể. Chưa kiểm chứng đủ
góc quay vì người dùng chưa thấy/làm theo toàn bộ hướng dẫn chẩn đoán. Không nới
ngưỡng danh tính hoặc hạ ngưỡng PAD dựa trên phép thử nhỏ này.

Frame PAD uncertain được bỏ qua theo cùng cơ chế retry có nonce/hash/max-gap/TTL,
reset hold hiện tại, không tính bằng chứng và không ghi DB. Spoof vẫn hủy ngay.
Sau response recognized có attendance đã lưu, web dừng gửi frame và giữ biên nhận
trong panel; người dùng bấm Quét người tiếp theo để bắt đầu thử thách mới. Ẩn box
cũ trên video còn chạy để không gắn danh tính đã lưu vào khuôn mặt mới trong ảnh.

Profiling trực tiếp cho thấy HOG tốn khoảng 400 ms/frame khi YuNet thấy mặt nhanh
hơn. Thêm backend tùy chọn yunet ưu tiên DNN; HOG chỉ cứu khi DNN không thấy mặt
hoặc thiếu model. Hybrid hiện hữu vẫn giữ cách hợp nhất hai detector. Không tự
chuyển mọi môi trường sang backend mới; local chỉ bật sau khi so khớp mẫu hiện hữu
trên camera. Giữ toàn bộ box DNN để chặn nhiều người, giữ PAD/quality trên ảnh gốc.
