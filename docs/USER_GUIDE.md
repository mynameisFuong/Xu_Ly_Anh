# Hướng dẫn sử dụng và trình diễn

## 1. Khởi động và đăng nhập

Làm các bước cài đặt tại [README](../README.md), sau đó chạy từ gốc dự án:

```powershell
.\.venv\Scripts\python.exe scripts/run_web.py --port 8765
```

Mở `http://127.0.0.1:8765/demo`. Không chỉ định `--port` thì dùng cổng 8000.
Tên môi trường `.venv` là ví dụ; nếu đã cài trong `.venv313` thì dùng đúng môi
trường đó. Giữ terminal backend hoạt động. Đổi `.env` cần khởi động lại server.

Giao diện web hiện dành cho **admin**. Seed mới tạo `admin/admin123`; seed không
đổi mật khẩu tài khoản có sẵn. Tài khoản teacher/device dùng API hoặc client phù
hợp, chưa có giao diện web riêng cho mọi vai trò. Phiên đăng nhập có hạn;
hết hạn sẽ chuyển về đăng nhập. Camera cần localhost hoặc HTTPS và được cấp quyền.

## 2. Chuẩn bị dữ liệu

Seed tạo ba lớp `[DEMO]`, 12 sinh viên và các buổi giả lập; ảnh và Face ID không
đi kèm. Các kết quả đúng/trễ/vắng có sẵn chỉ dùng minh họa nghiệp vụ.
Để demo một người thật, tạo hồ sơ riêng và ghi nhận sự đồng ý của người đó.

Trong **Sinh viên**, nhập MSSV, họ tên, lớp hành chính nếu cần, trạng thái đồng ý
và **Ghi danh vào lớp học**, rồi lưu. MSSV là duy nhất; hồ sơ đã xóa mềm vẫn
giữ mã đó. Khi thêm vào một lớp mới, ghi danh cũ không bị xóa.

**Lớp hành chính là nhãn hồ sơ**, ví dụ D22; **lớp học ghi danh** là lớp dùng lọc
danh tính khi điểm danh, ví dụ DEMO-IMG01. Chỉ điền lớp hành chính chưa tạo ghi danh.
Web hiện dùng lớp có sẵn; tạo lớp mới bằng API `POST /classes` qua OpenAPI hoặc
client API của bạn. Chưa có trang web quản lý đầy đủ tài khoản/lớp.

Nhập danh sách hàng loạt: tải mẫu CSV/Excel, điền thông tin, chọn lớp, **Xem trước**
rồi **Nhập sinh viên hợp lệ**. Dòng lỗi/trùng bị bỏ qua và có lý do. Đổi file
hoặc lớp phải xem trước lại. Nhập danh sách không nhập ảnh hay tự tạo Face ID.

## 3. Đăng ký Face ID

1. Vào **Khuôn mặt**, chọn đúng sinh viên đã đồng ý. Kiểm tra các lớp đã ghi danh.
   Nếu cần, chọn lớp và bấm **Ghi danh vào lớp** ngay tại đây.
2. Bấm **Bắt đầu quét 5 góc**; camera được mở tự động. Chỉ một người trong ảnh,
   mặt đủ sáng và nằm trọn khung. Không quay quá xa khiến mất mắt/mũi.
3. Lần lượt nhìn thẳng, quay trái, quay phải, ngẩng nhẹ và cúi nhẹ. Giữ mỗi góc
   trong vài giây để chờ server xử lý. Góc chính diện làm mốc cho các góc sau.
4. Tít ngắn lặp lại nghĩa là đang chờ, tít dài nghĩa là góc đã lưu; nhìn lại màn
   hình để đổi góc. Có hai giây nghỉ giữa các góc. Có thể tắt âm thanh bằng checkbox.
5. Khi đủ năm góc, kiểm tra trạng thái **Hoàn tất** và lớp đã ghi danh.

**Dừng quét** hủy lượt đang làm; bắt đầu lại sẽ quét từ góc đầu. Nếu đăng ký lại,
bộ Face ID đang hoạt động vẫn được giữ tới khi đủ bộ mới. **Tắt camera** giải
phóng thiết bị ngay và dừng lượt quét. Đổi trang cũng giải phóng camera.
Ẩn tab tạm ngừng gửi frame/âm thanh; không coi các góc đang chờ là đã hoàn thành.

Các trạng thái:

| Hiển thị | Ý nghĩa và cách xử lý |
| --- | --- |
| 0–4/5 góc | Chưa đủ mẫu theo profile hiện tại; hoàn thành lượt đăng ký mới. |
| Hoàn tất | Đủ năm góc cùng model/profile hiện tại; còn cần consent và ghi danh đúng lớp. |
| Cần quét lại · mẫu cũ | Có mẫu ở profile khác; đăng ký lại, không đổi nhãn vector cũ. |
| Chưa có engine Face ID | Cài engine theo README và khởi động lại backend; quản lý/thủ công vẫn dùng được. |

Quét nhiều góc là thu mẫu, **không phải liveness**. Hệ thống chưa chống ảnh in/video.

## 4. Mở buổi và quét điểm danh

Trong **Buổi học**, chọn lớp, ngày/giờ vào học và phút cho phép trễ. Ca sáng/chiều
chỉ gợi ý giờ; kiểm tra lại ngày giờ trước khi bấm mở. Mỗi lớp chỉ có một buổi
đang mở. Buổi seed có thể có giờ cũ, cần chỉnh cho tình huống trình diễn.

Mở trang **Điểm danh** của đúng buổi. Dòng kiểm tra Face ID chỉ tính sinh viên
được ghi danh trong lớp, còn consent và có bộ mẫu cùng profile. Nếu vừa đăng ký
ở tab khác, bấm **Làm mới** để cập nhật bảng và số người sẵn sàng.

Bấm **Bắt đầu quét** một lần. Camera tiếp tục chạy, nhiều người có thể vào/rời
khung. Khung vàng là đang chờ; khung xanh kèm tên nghĩa là server đã có bản ghi
điểm danh. Người đã ghi nhận có thể rời đi; người khác tiếp tục chờ. Camera có
thể xử lý chậm trên CPU; video mượt không có nghĩa model xử lý đủ mọi frame.

Một người chỉ có một bản ghi trong buổi. “Đã điểm danh trong buổi này” là kết
quả hợp lệ, không tạo thêm lượt. Log bên cạnh chỉ là hoạt động của lần mở trang,
giới hạn 12 dòng; bảng điểm danh trong DB mới là kết quả lưu lâu dài.

**Dừng quét** ngừng nhận diện nhưng để camera bật; **Tắt camera** ngừng cả hai.
Khi đổi/bỏ chọn buổi, quét và dữ liệu hiển thị của buổi trước được xóa khỏi màn
hình. Điều này không xóa bản ghi đã lưu trong DB.

## 5. Kết quả, điều chỉnh và đóng buổi

- Đến trước/bằng giờ vào học cộng thời gian cho phép: đúng giờ. Sau đó: đi trễ.
  Chưa có bản ghi vẫn là “Chờ điểm danh”, chưa tự kết luận vắng khi buổi đang mở.
- Dùng **Điều chỉnh** ở hàng sinh viên, chọn trạng thái và nhập lý do. Lỗi lưu
  hiển thị trong hộp thoại; nhập liệu được giữ để thử lại. Các thay đổi có audit.
- **Đóng buổi** cần xác nhận; người chưa có bản ghi được ghi vắng. Không thể
  tiếp tục quét tự động trong buổi đó. Muốn quét lại phải mở buổi mới.
- Trong **Buổi học → Buổi đã đóng**, bấm **Xem kết quả** để xem bảng, xuất CSV
  hoặc điều chỉnh thủ công có lý do. Lịch sử web giới hạn 100 buổi gần nhất.
  Trang của buổi đóng ẩn camera và khóa thay đổi chính sách giờ.
- Web xuất CSV (UTF-8 BOM); API còn có xuất XLSX. File phản ánh dữ liệu tại lúc xuất.

Sửa giờ/chính sách khi đang mở áp dụng cho lượt nhận diện sau đó; không tự tính
lại trạng thái các bản ghi đã lưu. Danh sách buổi dùng thành viên lớp hiện tại,
chưa có snapshot danh sách lịch sử; nên chốt và xuất kết quả trước khi sửa roster.

## 6. Xử lý lỗi thường gặp

| Tình huống | Cách xử lý |
| --- | --- |
| Đã quét đủ nhưng lớp báo chưa có Face ID | Kiểm tra MSSV, lớp học thực sự đã ghi danh, đúng buổi, consent và nhãn “mẫu cũ”. |
| Quay mãi chưa nhận góc | Quay nhẹ từ góc nhìn thẳng, giữ yên vài giây; tăng sáng phía trước, tránh mất mặt ở mép ảnh. |
| Mặt quá nhỏ/mờ/tối | Tiến gần, giữ yên, lau camera và đổi vị trí/ánh sáng. Không phóng to ảnh mờ để vượt quality gate. |
| Camera bị từ chối quyền | Cho phép camera trong thông tin trang của trình duyệt, tải lại và thử lại. |
| Camera không mở được | Đóng ứng dụng đang dùng camera, kiểm tra cáp và thiết bị được chọn. |
| Không kết nối server | Kiểm tra terminal backend, đúng cổng và URL; tải lại trang sau khi server chạy lại. |
| Luồng báo đang kết nối lại | Chờ hệ thống thử frame mới; kiểm tra server nếu kéo dài. Bản ghi đã lưu không bị xóa. |
| Máy khác pull về không thấy Face ID | Git không mang DB/ảnh/vector. Seed lại metadata hoặc chuyển metadata, rồi đăng ký camera trên máy đích. |

## 7. Kịch bản demo ngắn

Chuẩn bị lớp/buổi riêng, một người đã đăng ký và một người chưa đăng ký. Cho
hai người vào khung; người được ghi nhận rời đi, người mới bước vào. Kiểm tra
bảng không tăng trùng; minh họa điều chỉnh có lý do, đóng buổi, xem lại và xuất
CSV. Thu thời gian/kết quả bằng [quy trình thực nghiệm](THU_NGHIEM_DO_AN.md).
Không dùng bản ghi seed làm bằng chứng model đã nhận diện thành công.
