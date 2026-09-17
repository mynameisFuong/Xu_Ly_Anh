Bạn hãy đóng vai một **AI Solution Architect kiêm người hướng dẫn kỹ thuật cho Junior AI Engineer**.

Tôi là một junior đang xây dựng đồ án **“Hệ thống nhận diện khuôn mặt và điểm danh tự động”**. Hãy giúp tôi thiết kế kiến trúc hệ thống từ tổng quan đến chi tiết, có thể triển khai thực tế, thay vì chỉ liệt kê công nghệ.

**1. Bối cảnh và giới hạn**

* Đối tượng sử dụng: quản trị viên, giáo viên và sinh viên.
* Mục đích: quản lý lớp học, nhận diện sinh viên qua camera, ghi nhận điểm danh theo từng buổi và xuất báo cáo.
* Giả định ban đầu: tối đa 500 sinh viên, mỗi lớp khoảng 30–50 người, MVP sử dụng một camera tại vị trí điểm danh.
* Thiết bị ban đầu: laptop Windows và webcam; ưu tiên chạy được bằng CPU.
* Tôi có kiến thức Python, SQL và xử lý ảnh cơ bản, nhưng chưa có nhiều kinh nghiệm thiết kế hệ thống.
* Ngân sách hạn chế, ưu tiên công nghệ mã nguồn mở và triển khai cục bộ.
* Các con số trên là giả định thiết kế, không phải kết quả hiệu năng đã được kiểm chứng.

Nếu thiếu thông tin quan trọng, hãy hỏi tối đa 5 câu. Nếu tôi chưa trả lời, hãy công khai giả định hợp lý và tiếp tục thiết kế.

**2. Chức năng cần có**

Đăng ký khuôn mặt:

* Tạo hồ sơ sinh viên gồm mã sinh viên, họ tên và lớp.
* Thu nhận nhiều ảnh khuôn mặt với chất lượng phù hợp.
* Kiểm tra ảnh mờ, thiếu sáng, không có mặt hoặc có nhiều khuôn mặt.
* Trích xuất và lưu đặc trưng khuôn mặt gắn với đúng sinh viên.
* Có quy trình cập nhật, đăng ký lại và xóa dữ liệu khuôn mặt.

Điểm danh:

* Giáo viên chọn lớp và mở buổi điểm danh.
* Camera tiếp nhận hình ảnh và hệ thống nhận diện sinh viên.
* Ưu tiên tìm kiếm trong danh sách sinh viên của lớp đang điểm danh.
* Phân biệt người đã nhận diện, người chưa đăng ký và trường hợp chưa đủ tin cậy.
* Không ép một khuôn mặt lạ thành sinh viên có độ tương đồng cao nhất.
* Hạn chế nhận nhầm bằng cơ chế xác nhận qua nhiều khung hình.
* Mỗi sinh viên chỉ có một bản ghi điểm danh chính thức trong một buổi, dù được camera nhận diện nhiều lần.
* Ghi nhận thời điểm, trạng thái và nguồn điểm danh.
* Cho phép giáo viên xác nhận hoặc sửa thủ công, có lưu lịch sử thay đổi.
* Chỉ kết luận vắng sau khi buổi điểm danh đóng và đã đối chiếu danh sách lớp.

Quản lý và báo cáo:

* Quản lý tài khoản, sinh viên, lớp, danh sách thành viên và buổi học.
* Xem danh sách có mặt, đi muộn, vắng và các trường hợp cần kiểm tra.
* Thống kê theo sinh viên, lớp và khoảng thời gian.
* Xuất báo cáo CSV hoặc Excel.

**3. Yêu cầu thiết kế kiến trúc**

Hãy đề xuất một kiến trúc MVP phù hợp với năng lực junior. Ưu tiên sự đơn giản, dễ chạy, dễ gỡ lỗi; chỉ đưa thêm thành phần khi có lý do cụ thể.

Làm rõ trách nhiệm và cách giao tiếp giữa:

* Giao diện quản trị và điểm danh.
* Backend API.
* Thành phần thu nhận camera.
* Pipeline xử lý và nhận diện khuôn mặt.
* Cơ sở dữ liệu nghiệp vụ.
* Nơi lưu ảnh hoặc embedding.
* Thành phần ghi log và theo dõi lỗi.

Nêu rõ camera kết nối với máy nào, quá trình suy luận AI chạy ở đâu, ảnh được truyền theo cách nào và thành phần nào có quyền ghi bản ghi điểm danh.

Phân biệt kiến trúc triển khai cục bộ một camera với phương án mở rộng nhiều camera. Không mặc định cần microservices, Kubernetes, message broker hoặc vector database.

**4. Thiết kế pipeline AI**

Trình bày từng bước:

Thu nhận khung hình → phát hiện khuôn mặt → kiểm tra chất lượng → căn chỉnh → trích xuất embedding → so khớp → xác nhận theo thời gian → ghi nhận điểm danh.

Với từng bước, hãy nêu:

* Đầu vào và đầu ra.
* Thuật toán hoặc thư viện phù hợp.
* Lý do lựa chọn.
* Lỗi có thể xảy ra và cách xử lý.

Phân biệt rõ face detection, face recognition và liveness detection.

Đề xuất một phương án công nghệ chính và tối đa một phương án thay thế. Kiểm tra khả năng chạy trên Windows/CPU và giấy phép của cả mã nguồn lẫn trọng số mô hình. Nếu chưa xác minh được, hãy nói rõ.

Giải thích cách chọn ngưỡng so khớp bằng dữ liệu kiểm thử. Không đưa một ngưỡng cố định rồi coi là đúng cho mọi mô hình.

Đề xuất cách xử lý giả mạo bằng ảnh hoặc video; nêu rõ giới hạn của MVP. Không coi chớp mắt hoặc quay đầu đơn thuần là bằng chứng chống giả mạo chắc chắn.

**5. Thiết kế cơ sở dữ liệu**

Đề xuất các bảng tối thiểu, có thể điều chỉnh tên nếu hợp lý:

* Users
* Students
* Classes
* ClassEnrollments
* ClassSessions
* FaceTemplates
* AttendanceRecords
* AuditLogs

Với mỗi bảng, trình bày trường chính, kiểu dữ liệu, khóa chính, khóa ngoại, quan hệ và ràng buộc.

Đặc biệt:

* Có ràng buộc duy nhất trên cặp sinh viên–buổi học để chống điểm danh trùng ở mức cơ sở dữ liệu.
* Phân biệt sự kiện nhận diện với kết quả điểm danh chính thức.
* Lưu phiên bản mô hình gắn với embedding để tránh so khớp dữ liệu không tương thích.
* Giải thích nên lưu ảnh và embedding ở đâu, khi nào có thể không cần giữ ảnh gốc.

Vẽ ERD bằng Mermaid.

**6. Thiết kế API và các luồng xử lý**

Liệt kê các API quan trọng, gồm:

* HTTP method và đường dẫn.
* Mục đích.
* Quyền truy cập.
* Request/response mẫu ngắn.
* Lỗi chính.

Mô tả tuần tự ba luồng:

1. Đăng ký khuôn mặt.
2. Mở buổi và điểm danh tự động.
3. Sửa điểm danh thủ công và xuất báo cáo.

Làm rõ cách chống ghi trùng khi gửi lại yêu cầu hoặc khi nhiều khung hình cùng nhận diện một sinh viên.

**7. Bảo mật, quyền riêng tư và lỗi vận hành**

Thiết kế các biện pháp phù hợp cho dữ liệu khuôn mặt:

* Thông báo và ghi nhận sự đồng ý trước khi thu thập.
* Có phương án điểm danh thủ công cho người không sử dụng khuôn mặt.
* Phân quyền truy cập ảnh, embedding và báo cáo.
* Không coi embedding là dữ liệu vô danh.
* Xác định thời gian lưu giữ và quy trình xóa.
* Không ghi ảnh hoặc embedding vào log thông thường.

Giải thích cách xử lý khi camera mất kết nối, không nhận diện được, nhận nhầm, backend khởi động lại hoặc cơ sở dữ liệu không ghi được. Không hiển thị “điểm danh thành công” khi chưa lưu thành công.

**8. Kế hoạch kiểm thử và triển khai**

Đề xuất kiểm thử với:

* Ánh sáng và góc mặt khác nhau.
* Người đeo kính hoặc thay đổi ngoại hình.
* Người chưa đăng ký.
* Nhiều người xuất hiện trong khung hình.
* Điểm danh lặp lại.
* Ảnh chụp hoặc video giả mạo.
* Lỗi camera và lỗi ghi dữ liệu.

Nêu cách đo tỷ lệ nhận nhầm, tỷ lệ bỏ sót, độ trễ và khả năng chạy trên CPU. Tách dữ liệu đăng ký khỏi dữ liệu đánh giá; không dùng lại chính ảnh đăng ký để kết luận độ chính xác.

Đưa ra lộ trình theo từng giai đoạn, với đầu ra và tiêu chí hoàn thành:

1. Pipeline nhận diện độc lập.
2. Cơ sở dữ liệu và backend.
3. Giao diện và tích hợp điểm danh.
4. Kiểm thử, bảo mật và hoàn thiện báo cáo.

Đề xuất cấu trúc thư mục dự án và cách chạy hệ thống trên máy Windows.

**9. Định dạng câu trả lời**

Hãy trình bày theo thứ tự:

1. Giả định và phạm vi MVP.
2. Kiến trúc đề xuất và sơ đồ Mermaid.
3. Bảng công nghệ, vai trò và lý do chọn.
4. Pipeline AI.
5. Cơ sở dữ liệu và ERD.
6. API và các luồng nghiệp vụ.
7. Bảo mật và xử lý lỗi.
8. Kiểm thử và lộ trình triển khai.

Giải thích thuật ngữ khi xuất hiện lần đầu. Với mỗi quyết định quan trọng, nêu vì sao phù hợp với một junior và giới hạn của lựa chọn đó. Phân biệt mục tiêu hiệu năng với kết quả đã đo.

Ở bước này, hãy tập trung thiết kế kiến trúc; chỉ dùng pseudocode hoặc đoạn mã ngắn khi cần làm rõ logic, chưa viết toàn bộ ứng dụng.
