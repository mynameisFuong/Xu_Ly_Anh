# Kiểm thử đồ án với camera

Mục tiêu là đo được kết quả trên máy trình diễn, không suy rộng thành độ chính xác
chung của model. Chỉ thu dữ liệu với sự đồng ý; dùng mã P01, P02… thay tên thật
trong bảng báo cáo và không đưa ảnh khuôn mặt lên Git.

## Chuẩn bị

1. Mời khoảng 5–10 người; ghi cấu hình máy, camera, độ phân giải, ánh sáng và
   profile tiền xử lý đang sử dụng. Tạo lớp và đăng ký đủ năm góc cho từng người.
2. Ghi mẫu đăng ký và ảnh/stream kiểm tra ở **hai lần khác nhau**. Dành một vài
   người chưa đăng ký để thử người lạ. Không dùng lại chính frame đăng ký làm test.
3. Mở buổi thử và đánh dấu chính xác danh tính người có mặt để đối chiếu; dữ liệu
   test nên dùng một lớp/buổi riêng để không ảnh hưởng bảng điểm thật.

## Đo nhận diện và tốc độ

Trước khi đo điểm danh, đo riêng thời gian hoàn tất năm góc, số lần phải bắt đầu
lại và người dùng có hiểu tiếng tít/hướng dẫn hay không. Ghi số người hoàn tất
trên tổng số người thử, không chỉ chọn các lượt thuận lợi.

Thử lần lượt một người, hai người và 3–4 người cùng khung hình. Với mỗi người,
ghi thời điểm vào khung, thời điểm được ghi nhận hoặc kết thúc chờ, kết quả đúng,
nhầm hay không nhận diện được. Thử thêm ánh sáng yếu, đeo kính và góc quay nhẹ;
cho một người đã ghi nhận rời đi và người mới bước vào. Kiểm tra không tạo bản
ghi trùng, đúng/trễ/vắng, điều chỉnh thủ công và xuất báo cáo.

Mẫu bảng ghi (tạo bản sao riêng cho từng lượt):

| Lượt | Mã người | Số người trong khung | Điều kiện | Kết quả đúng/nhầm/bỏ sót | Thời gian đến ghi nhận (giây) | Ghi chú |
| --- | --- | ---: | --- | --- | ---: | --- |
| 1 | P01 | 1 | Bình thường |  |  |  |

Tổng hợp số lượt đúng, nhầm, bỏ sót; với người lạ ghi rõ số lần bị nhận nhầm.
Báo thời gian trung bình và lớn nhất theo số người trong khung. Ghi tổng số lượt
và điều kiện đo để người đọc hiểu giới hạn của mẫu thử nhỏ.

## So sánh tiền xử lý

Dùng cùng tập ảnh gốc, cùng ngưỡng và model, so sánh `legacy`, `v1`, `v2-adaptive`,
`v3-adaptive` (phiên bản hiện hành).
Tạo manifest theo [hướng dẫn benchmark](PREPROCESSING_BENCHMARK.md), chia ảnh
đăng ký và kiểm tra khác phiên; dành tập test riêng nếu đủ người. Chạy:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_preprocessing.py storage/recognition-benchmark/manifest.json --partition validation --profiles legacy v1 v2-adaptive v3-adaptive --max-side 640 --output storage/recognition-benchmark/validation.json
```

Đọc số probe nhận đúng/nhầm/bị từ chối, lý do từ chối và thời gian xử lý theo
từng cấu hình. Đặt bảng kết quả cùng một vài ảnh minh họa được phép chia sẻ vào
báo cáo; không kết luận phương pháp nào tốt hơn nếu mẫu quá ít hoặc chênh lệch
nhỏ. Công cụ này đo xử lý ảnh ngoại tuyến, không đo độ trễ toàn bộ camera đến UI.

Với dữ liệu validation, chọn cấu hình và ngưỡng trước; nếu có tập test độc lập,
chạy tiếp theo hướng dẫn benchmark với calibration validation. Không tự đổi profile
đang dùng nếu chưa kiểm tra tính tương thích mẫu Face ID đã đăng ký.

## Kiểm thử người dùng

Kiểm tra thêm xem lại buổi đã đóng, tải CSV, lỗi camera bị từ chối quyền, bỏ chọn
buổi không còn thống kê cũ, mẫu khác profile được báo cần quét lại. Thao tác theo
[USER_GUIDE](USER_GUIDE.md); đối chiếu các ca tự động ở [EVALUATION](EVALUATION.md).

Mời 2–3 người chưa tham gia phát triển tự làm theo hướng dẫn từ đăng nhập đến
xuất báo cáo. Ghi bước bị vướng và thời gian hoàn thành; đặc biệt hỏi liệu họ
hiểu tiếng tít ngắn/dài, hướng quay và thông báo khi khuôn mặt bị tối/mờ không.

Các chỉ số thực tế chỉ điền sau khi đo. Hệ thống không có liveness/PAD, vì vậy
không kết luận có khả năng chống ảnh in hoặc video phát lại từ các phép thử này.

## Kết quả smoke test ngày 31/10/2026

Chạy lại ba profile trên ảnh ví dụ công khai đã có ở máy: một ảnh đăng ký,
bốn probe cùng người (gồm ba biến thể tổng hợp) và một probe người lạ. Kết quả:
`legacy` nhận đúng 3/4 probe cùng người; `v1` và `v2-adaptive` nhận đúng 4/4.
Probe người lạ không bị nhận nhầm ở cả ba profile. Probe xoay 90° không được
detector tìm thấy ở `legacy`. Mẫu quá nhỏ để kết luận độ chính xác, FAR hay ưu
thế tốc độ; chưa có đo người thật hoặc camera trực tiếp. Báo cáo JSON được lưu
local trong `storage/preprocessing-smoke/comparison-20261031.json`.

Kiểm tra trích xuất riêng với cùng hai ảnh ví dụ, ghép thành frame một mặt và
hai mặt: sau một lượt làm nóng tương ứng, một mặt mất khoảng 1,59 giây, hai mặt
khoảng 3,18 giây; cả hai mặt được phát hiện và trích xuất thành công. Đây là hai
phép đo đơn lẻ trên CPU hiện tại, không gồm mạng, DB hoặc màn hình, không phải
FPS camera hay kết quả cho nhóm người thật.
