# Nâng cấp xác nhận và đánh giá điểm danh

## Các thay đổi đã triển khai

- Xác nhận theo thời gian: ba lần khớp mới, cách nhau ít nhất 250 ms và kéo dài
  ít nhất 500 ms theo mặc định. Mất quan sát quá 10 giây phải bắt đầu lại.
  Ảnh trùng nội dung trong 128 frame gần nhất bị từ chối, kể cả đổi frame_id.
- Tracker dùng IoU, dự đoán dịch chuyển và embedding dlib để ghép người.
  Khoảng cách embedding quá lớn không được kế thừa track; ghép hình học mơ hồ
  xóa phiếu xác nhận liên quan. Trường hợp vượt ngân sách vẫn phải có embedding
  mới trước khi được xác nhận. Đây là biện pháp nhất quán track, không phải PAD.
- So khớp nhiều mặt bằng ma trận; gallery được chuẩn bị một lần mỗi frame.
  Tối đa 16 probe × 512 template cho một block tạm. Ngưỡng, margin và cách lấy
  mẫu gần nhất của mỗi danh tính được giữ nguyên để không đổi profile đã đăng ký.
- Ở luồng ảnh gốc không bật tiền xử lý, chuyển BGR sang RGB một lần cho các
  lượt encode mặt của frame, thay vì chuyển lại toàn ảnh cho từng mặt.
- API có `timings_ms.inference`, `gallery`, `matching`. Consent, mẫu đang hoạt
  động và danh sách lớp vẫn được đọc lại mỗi frame, tránh cache quyền đã bị thu hồi.
- Các API scan không cho histogram dự phòng ghi điểm danh. Nếu thiếu dlib Face ID,
  trả lỗi rõ ràng thay vì âm thầm dùng biểu diễn không phù hợp.
- Ảnh minh chứng mới chỉ lưu crop box của mặt đã xác nhận dưới dạng JPEG.
  Không thay đổi ảnh cũ. Nếu các mặt che nhau, crop vẫn có thể chứa một phần người
  khác; không nên coi crop là kỹ thuật ẩn danh.
- Web và desktop dùng bearer token có hạn dùng và thu hồi khi đăng xuất;
  database chỉ lưu hash token. Bỏ xác thực bằng `X-User-Id`. Mật khẩu mới dùng
  PBKDF2 có salt; SHA-256 cũ được nâng cấp khi đăng nhập thành công.
- Giảng viên chỉ đọc/điều khiển lớp và phiên được giao. Tài khoản thiết bị cần
  quyền lớp riêng. Admin cấp/thu hồi bằng `PUT` / `DELETE
  /classes/{class_id}/devices/{user_id}`. Seed demo cấp device01 vào IMG101;
  không tự cấp quyền cho thiết bị với mọi lớp đang có.

Đổi code không yêu cầu đăng ký lại khuôn mặt: trọng số và profile embedding
hiện tại được giữ nguyên. Server tạo thêm bảng phiên đăng nhập và quyền lớp khi
khởi động; không xóa dữ liệu cũ. Trình duyệt đang giữ tài khoản dạng cũ sẽ yêu cầu
đăng nhập lại một lần. Desktop cũ dùng X-User-Id cần cập nhật cùng backend.

## Cấu hình

```dotenv
AUTH_SESSION_HOURS=8
ATTENDANCE_MIN_HITS=3
STREAM_CONFIRMATION_WINDOW_SECONDS=30
STREAM_MIN_OBSERVATION_INTERVAL_SECONDS=0.25
STREAM_MIN_CONFIRMATION_SECONDS=0.5
STREAM_MAX_OBSERVATION_GAP_SECONDS=10
STREAM_MAX_FACES_PER_FRAME=8
```

Ba lần quan sát là mức tối thiểu, không phải bảo đảm xác suất sai giảm lũy thừa:
các frame liên tiếp có tương quan. Cần đánh giá camera thực trước khi thay đổi
ngưỡng khoảng cách, margin, thời gian giữ hoặc model.

## Đánh giá dữ liệu thực tế, không ghi DB

`scripts/evaluate_stream.py` đọc ảnh đã gán nhãn theo thứ tự thời gian, dùng
pipeline đang cấu hình để trích xuất embedding, so khớp và xác nhận nhiều người.
Không kết nối DB điểm danh, lưu ảnh đầu vào hay xuất embedding/danh tính trong báo cáo.
Chỉ dùng dữ liệu được phép xử lý; subject trong manifest nên là mã ẩn danh.

Schema ví dụ ở [stream-evaluation.example.json](examples/stream-evaluation.example.json).
Các đường dẫn ảnh là chỗ điền dữ liệu của bạn, không có ảnh người đi kèm repo.
Mỗi danh tính đã đăng ký cần năm mẫu đủ chất lượng với năm pose khác nhau.
Frame kiểm tra có thể chứa cả người đã đăng ký và người lạ. Box dùng tọa độ
`[x,y,width,height]` theo ảnh đã áp EXIF, khớp hệ tọa độ API. Timestamp là giây
trong clip, bắt đầu từ số không hoặc số không âm khác và tăng nghiêm ngặt.

```bash
python scripts/evaluate_stream.py /path/to/manifest.json \
  --partition validation --output storage/reports/stream-validation.json
```

Chọn ngưỡng trên validation; giữ cố định model và tham số khi chạy test. Danh tính
validation và test phải tách nhau; buổi đăng ký và buổi kiểm tra cũng phải khác.
Loader chặn trùng nội dung ảnh giữa enrollment và probe, giữa các phân vùng hoặc
buổi kiểm tra. Frame đóng băng trong cùng stream không được tính thêm bằng chứng.
Hệ thống có sẵn benchmark tiền xử lý để hiệu chỉnh ngưỡng và so sánh profile;
xem [PREPROCESSING_BENCHMARK.md](PREPROCESSING_BENCHMARK.md).

Báo cáo stream gồm:

- Số lượt điểm danh đúng, nhầm, bỏ sót; precision và recall theo lượt người/buổi.
- Số mặt gán nhãn được detector tìm thấy ở IoU ≥ 0,5.
- Số lần một người gán nhãn đổi track_id, bao gồm cả phân mảnh sau mất mặt;
  chỉ số này không đồng nghĩa mọi lần đổi track là gán nhầm danh tính.
- p50/p95 thời gian đến lúc xác nhận, tính từ lần đầu người hợp lệ có nhãn xuất hiện.
- p50/p95 thời gian suy luận + so khớp + tracking; thống kê theo điều kiện cảnh.

Đây là replay ngoại tuyến: không đo độ trễ mạng, JPEG từ trình duyệt, thời gian
ghi DB hay độ trễ camera đến màn hình. Không dùng nó để công bố FPS toàn hệ thống.
Đặc biệt, không dùng kết quả replay này để công bố khả năng chống ảnh in/video.

## Kiểm chứng và phần còn cần dữ liệu

Phép đo tổng hợp trên máy local ngày 2026-10-30: 8 probe, 40 danh tính × 5 mẫu,
128 chiều, 50 lượt sau warm-up. Lượt đo cuối: bản cũ p50 khoảng 3,21 ms;
bản ma trận khoảng 0,64 ms, tính cả chuẩn bị gallery. Đây là microbenchmark với vector giả,
không đo độ chính xác nhận diện hoặc mức tăng tốc của toàn bộ camera pipeline.

Các test kiểm tra phiên hết hạn/thu hồi, giả mạo header, quyền lớp, frame lặp,
frame dồn dập, đổi người/cắt ngang, so khớp ma trận với bản tham chiếu, crop minh
chứng và lỗi rò dữ liệu trong bộ đánh giá. Test browser dùng camera tổng hợp.

Chưa đổi sang model mới hoặc thêm PAD chưa được đo. Luồng hiện tại vẫn chưa
chứng minh chống được ảnh in, video phát lại, camera ảo hoặc deepfake. Bước tiếp
theo là thu bộ validation/test thực tế có sự đồng ý, đo PAD riêng và chỉ thay model
khi cải thiện chỉ số trên thiết bị đích. Điểm danh có người giám sát và điều chỉnh
thủ công vẫn cần thiết trong giai đoạn này.
