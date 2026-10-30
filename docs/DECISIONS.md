# Quyết định kiến trúc và thuật toán hiện hành

Tổng hợp ngày 31/10/2026. Các thiết kế PAD/nhân viên ở lịch sử Git đã được thay
bằng phạm vi hiện tại. [Đặc tả gốc](../faceid-attendance-spec.md) là nguồn yêu cầu
lịch sử, không là cam kết hệ thống đã có mọi công nghệ/chỉ tiêu trong đó.

## Giữ kiến trúc local cho bài tập lớn

FastAPI + SQLAlchemy + SQLite, web HTML/CSS/JavaScript, desktop Tkinter và worker
Python cùng dùng API. Không đưa Redis, PostgreSQL/pgvector, MinIO hoặc dịch vụ AI
tách rời vào demo khi chưa có nhu cầu thực tế. Đánh đổi: trạng thái xác nhận ở
RAM một process; file ảnh và DB không chung transaction; chưa có snapshot roster.

## Dùng model pretrained, giữ xử lý ảnh cổ điển thành module riêng

Dlib ResNet trả vector 128D và có căn chỉnh face chip nội bộ. Dự án không train
lại ResNet; đăng ký chỉ bổ sung mẫu đối chiếu. Module ảnh nhận BGR uint8 và trả
ảnh cùng định dạng trước encode. V3 là mặc định enforce; v1/v2 còn để đối chiếu.
Thay tham số ảnh ảnh hưởng profile thì đăng ký lại, không đổi nhãn vector cũ.

## Tăng cường có điều kiện và giữ nguồn làm bằng chứng chất lượng

Đo kích thước/độ nét/ánh sáng trên pixel nguồn trước resize/warp/tăng sáng. V3
chọn gamma hoặc CLAHE theo ROI, feather vùng đệm; không chạy mọi bộ lọc trên mọi
ảnh. Cứu ảnh tối chỉ khi còn đủ chi tiết và kiểm tra lại. Căn mắt ngoài, median
và bilateral là tùy chọn; mặc định không bật vì có thể làm mất texture hoặc nội
suy thêm. Kirsch, Retinex và Tan–Triggs không thay ảnh màu đầu vào runtime.

## Giảm khó khăn khi đăng ký

Góc chính diện làm mốc yaw/pitch để giảm ảnh hưởng vị trí camera. Quay nhẹ và
giữ yên được chấp nhận theo ngưỡng hướng dẫn trong [IMAGE_PROCESSING](IMAGE_PROCESSING.md).
Mặc định một jitter thay vì ba để giảm thời gian CPU, vẫn cần năm góc khác nhau.
Ngưỡng khoảng cách nhận diện 0,52/margin 0,04 không được nới theo thay đổi UX này.
Mẫu cũ hoạt động đến khi đủ bộ mới; API chuyển bộ trong một transaction.

## Điểm danh là luồng liên tục nhiều người

Mỗi frame có nhiều ROI; gallery giới hạn đúng lớp, consent, profile. Match mới
qua nhiều frame mới được ghi; tracker chỉ ghép quan sát, không dùng danh tính
cache để tạo điểm danh. Một request đang xử lý mỗi stream để không xếp hàng ảnh
cũ. Bảng và log cập nhật sau ghi nhận, video tiếp tục chạy. Không hứa FPS cố định.

## Tách dữ liệu lưu lâu dài và phản hồi tạm trên màn hình

Khung xanh cần attendance đã có trong response. Overlay hết hạn hoặc pixel live
đổi thì ẩn danh tính cũ; đây là vệ sinh hiển thị, không phải PAD. Log web giới hạn
12 dòng và mất khi tải lại; bảng DB và audit mới là dữ liệu lưu. Buổi đóng được
xem/xuất/điều chỉnh thủ công, nhưng không quét tự động hoặc sửa chính sách giờ.

## Phân biệt lớp hành chính, ghi danh lớp và Face ID

class_label là nhãn, ClassEnrollment là quan hệ học lớp, FaceTemplate là mẫu.
Ba dữ liệu không thay nhau. Giao diện hiển thị lớp ghi danh tại trang Face ID,
có thao tác thêm lớp và cảnh báo mẫu khác profile; tránh báo hoàn tất chung chung
khi buổi điểm danh thực tế không có gallery hợp lệ.

## Gỡ liveness/PAD theo yêu cầu

Ngày 30/10/2026 gỡ HOG/DFT-SVM PAD, MiniFASNet, model loader, train/evaluate PAD
và thử thách web. HOG detector vẫn dùng phát hiện mặt, không phân biệt người thật
và ảnh in. Các khóa LIVENESS_*/WEB_LIVENESS_* cũ bị bỏ qua để file môi trường cũ
không chặn khởi động; không thể dùng chúng để kích hoạt lại tính năng đã gỡ.

## Xác thực và dữ liệu nhạy cảm

Bearer token có hạn/thu hồi, DB lưu hash; mật khẩu PBKDF2 có salt, hỗ trợ nâng
cấp hash cũ lúc đăng nhập. Worker dùng camera token riêng, không đưa secret vào
frontend. Ảnh/vector/DB không theo Git. Xóa mềm/thu hồi không đồng nghĩa xóa vật
lý, nên chưa coi đây là giải pháp quản trị dữ liệu sinh trắc production đầy đủ.

## Cấu hình và tái lập

Launcher local đọc .env với override để tránh terminal IDE giữ biến cũ; Uvicorn
chạy trực tiếp vẫn theo ưu tiên environment của Pydantic. Script seed tạo metadata
giả lập lặp được, không tạo Face ID; chuyển dữ liệu bằng JSON không ảnh/vector.
Lệnh chạy, phiên bản mã, profile và điều kiện đo phải đi cùng kết quả báo cáo.
