> Tài liệu lịch sử: liveness/PAD đã được gỡ theo yêu cầu ngày 30/10/2026.
> Nội dung/kết quả bên dưới thuộc phiên bản trước, không phải hướng dẫn vận hành
> hiện hành. Xem [pipeline hiện tại](FACE_ANALYSIS.md) và
> [kế hoạch preprocessing](PREPROCESSING_UPGRADE_PLAN.md).
> Các bước train/evaluate trong tài liệu là thiết kế cũ, không chạy được bằng
> repository hiện tại. Không cần tải dataset PAD để cài hoặc demo hệ thống.

# Chọn dữ liệu huấn luyện và đánh giá PAD

## Kết luận

**Replay-Attack (Idiap)** là lựa chọn đầu tiên cho baseline chống ảnh in và video
phát lại của ứng dụng webcam này. Bộ gốc có 1.300 video RGB từ 50 người, gồm lần
truy cập thật, ảnh in và ảnh/video hiển thị trên màn hình; các nhóm train,
development và test không trùng người. Video được ghi bằng webcam laptop ở
320 × 240 px, gần với luồng camera web hơn ảnh chân dung tĩnh.

- Trang chính thức: https://www.idiap.ch/en/dataset/replay-attack
- Bản phát hành và điều kiện truy cập: https://zenodo.org/records/4593128

Tệp bị giới hạn truy cập. Idiap yêu cầu EULA cho nghiên cứu phi thương mại, người
ký có vị trí thường trực tại tổ chức và email học thuật/chuyên môn cùng tổ chức.
Không lấy bản sao từ nguồn phát lại không có quyền phân phối. Chưa có dữ liệu
Replay-Attack được tải vào dự án và chưa có model HOG/DFT-SVM được huấn luyện.

## Bối cảnh phiên bản cũ khi chọn dữ liệu

Engine nhận diện đang chạy là `ageitgey-face-recognition-dlib-resnet`, sinh
embedding 128 chiều và landmarks 68 điểm. Đây là trọng số dlib đã huấn luyện
sẵn; ảnh đăng ký trong hệ thống chỉ dùng làm template đối chiếu danh tính.
Chúng không mang nhãn tấn công `print`/`replay` và không đủ để huấn luyện PAD.

Ở phiên bản cũ, backend từng cấu hình `LIVENESS_BACKEND=minifasnet` với trọng số pretrained.
`train_liveness.py` (đã gỡ) huấn luyện **backend khác**:
HOG + DFT + SVM. Nó không fine-tune dlib hoặc MiniFASNet. Đầu vào của script
là ảnh BGR từ camera, có đúng một mặt, mặt tối thiểu 80 px và đạt quality gate.
[`test_preprocessing.py`](../tests/test_preprocessing.py) chỉ kiểm tra hình học,
ánh sáng và tính thuần của tiền xử lý; không chứa dữ liệu PAD.

## Chuẩn bị Replay-Attack sau khi được cấp quyền

1. Dùng đúng phân vùng `train`, `devel`, `test` của tác giả; ánh xạ `devel` thành
   `validation`. Không đưa video `enroll` vào huấn luyện PAD.
2. Giữ nguyên video gốc trong thư mục dữ liệu cục bộ không theo dõi bởi Git.
   Trích vài frame cách đều từ **mỗi video**, giữ ảnh camera đầy đủ và độ phân
   giải gốc. Không tách frame cùng video hoặc cùng người sang nhiều split.
3. Gán `live` cho truy cập thật, `print` cho ảnh giấy, `replay` cho video phát
   trên màn hình. Ảnh tĩnh hiển thị trên màn hình là một kiểu tấn công khác;
   đánh giá riêng, không âm thầm gọi là video replay.
4. Tạo CSV `path,label,split,subject_id,session_id` với `subject_id` là danh
   tính trong bộ dữ liệu và `session_id` nhận diện video nguồn. Đường dẫn ảnh
   tính tương đối từ CSV. Mỗi split phải có đủ ba nhãn.
5. Loại frame không giải mã được, có 0 hoặc nhiều hơn 1 mặt, mặt quá nhỏ/tối/
   sáng/nhòe; báo số lượng loại theo split và nhãn. Tránh chọn frame theo kết
   quả mô hình để không làm lệch benchmark. Kiểm tra trùng nội dung và người
   trùng split trước huấn luyện.
6. Chạy `train_liveness.py` vào thư mục model **mới**; script cố định ngưỡng
   trên validation và chỉ dùng test để báo cáo. Xem APCER riêng cho print và
   replay, BPCER, số lượng mẫu và sai số theo *video*, không chỉ theo frame.
7. Đánh giá thêm trên camera/thiết bị và ánh sáng của ứng dụng. Giữ
   `approved_for_enforcement=false` đến khi kiểm chứng thực địa đạt yêu cầu.
   Muốn thử model mới phải đổi `LIVENESS_BACKEND=hog-svm` và
   `LIVENESS_MODEL_DIR`; không thay model nhận diện dlib.

## Phương án bổ sung

- **OULU-NPU** có 4.950 video từ 55 người, ảnh in và video replay, sáu điện
  thoại, nhiều điều kiện sáng, với tập train/development/test tách người. Hợp
  để kiểm tra chéo miền camera sau Replay-Attack; cũng cần EULA và người ký
  thuộc viện nghiên cứu. Nguồn: https://sites.google.com/site/oulunpudatabase/welcome
- **CelebA-Spoof** có 625.537 ảnh từ 10.177 người, nhãn ảnh in/màn hình và
  góc nhìn đa dạng; tác giả cho tải công khai nhưng chỉ dùng nghiên cứu phi
  thương mại và cấm phân phối lại. Bản Google Drive gồm 74 phần ZIP, khoảng
  1 GB/phần. Ảnh live lấy từ CelebA còn spoof được thu riêng, nên dễ học khác
  biệt nguồn ảnh thay vì dấu hiệu tấn công trên webcam. Chỉ dùng để thăm dò
  hoặc bổ trợ sau khi kiểm tra lệch miền, không dùng làm bằng chứng duy nhất
  để bật enforcement. Nguồn: https://mmlab.ie.cuhk.edu.hk/projects/CelebA/CelebA_Spoof.html

Không dùng ảnh đăng ký sinh viên hoặc ảnh chứng cứ điểm danh làm bộ PAD nếu
chưa có nhãn tấn công, sự đồng ý và quy trình chia theo người/phiên rõ ràng.
