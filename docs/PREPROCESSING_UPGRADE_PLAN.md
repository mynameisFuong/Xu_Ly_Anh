# Kế hoạch nâng cấp tiền xử lý ảnh cho nhận diện điểm danh

Ngày lập: 30/10/2026. Phạm vi: xử lý ảnh cổ điển có cơ sở học thuật,
giữ engine nhận diện dlib ResNet 128D và cơ chế điểm danh hiện có.
Kế hoạch đã được duyệt triển khai. Các nhánh v2/v3 và công cụ đánh giá đã được
cài đặt; `.env.example` hiện mặc định v3 enforce. Khi cần thí nghiệm, v1 có thể
lấy mẫu đối chiếu v2/v3. Vector khác profile không được ghép chung.
Chưa có đủ dữ liệu camera để khẳng định mức cải thiện accuracy.

## Trạng thái sau triển khai

| Hạng mục | Trạng thái |
|---|---|
| P0: gỡ liveness/PAD | Đã hoàn tất. |
| P1: EXIF/hình học, chất lượng gốc, ROI gamma/CLAHE, profile v2 | Đã cài đặt và kiểm thử; v1 giữ nguyên hash. Dlib tự căn face chip mặc định. |
| P1: baseline/ablation recognition | Đã có CLI tách session/identity, FMR/FNMR/FPIR, độ trễ, bootstrap theo người; cần bộ camera thật để nghiệm thu. |
| P2: median/bilateral, thông báo chụp lại, shadow lấy mẫu | Đã cài đặt; denoise mặc định off. Xác nhận nhiều frame mới và reset khi đổi người vẫn được giữ. |
| P2: chọn frame/cache camera riêng | Đã có tracker theo geometry, chuyển động và embedding; xác nhận danh tính vẫn cần so khớp frame mới. Cần đo camera thực. |
| P3: Retinex/Tan–Triggs | Đã cài đặt ở nhánh benchmark độc lập; không có công tắc production. |
| P3: hiệu chuẩn/undistort | Chưa áp dụng: chưa có intrinsics đo của camera. Không tự tạo tham số giả định. |
| Chuyển bộ mẫu | Dữ liệu thử local đã được trích xuất lại bằng v3 từ ảnh chân dung còn lưu; vector v1 đã xóa. Máy khác không có ảnh nên cần đăng ký từ camera. CLI inventory vẫn chỉ đọc. |

Chi tiết lệnh chạy, cấu trúc dữ liệu và rollback:
[PREPROCESSING_BENCHMARK.md](PREPROCESSING_BENCHMARK.md).

Bổ sung theo yêu cầu luồng điểm danh nhiều người: đăng ký vẫn yêu cầu một mặt,
còn điểm danh stream xử lý nhiều ROI độc lập, giữ nguyên profile và vector 128D.
Chi tiết triển khai tại [STREAM_RECOGNITION.md](STREAM_RECOGNITION.md).

## 1. Kết quả đọc mã nguồn

- [recognition.py](../ai_pipeline/recognition.py) giải mã bytes bằng OpenCV,
  dùng BGR uint8, chuyển RGB khi gọi dlib và trả embedding float32 128 chiều.
  Engine histogram 256 chiều là fallback demo, không đủ Face ID đa góc.
- [detection.py](../ai_pipeline/detection.py) có HOG/YuNet/hybrid. YuNet hỗ trợ
  tìm mặt khó, không thay trọng số nhận diện. Giữ tất cả box; chỉ đăng ký mẫu mới từ chối nhiều mặt.
- [analysis.py](../ai_pipeline/analysis.py) gọi detector, ánh xạ box về ảnh gốc,
  đo chất lượng pixel gốc, ước lượng pose, căn mắt/CLAHE rồi encode.
- [preprocessing.py](../ai_pipeline/preprocessing.py) đã có mirror cấu hình,
  xoay 90/180/270, tìm roll ±20/±40, căn mắt, CLAHE trên Y và Kirsch chẩn đoán.
- [quality.py](../ai_pipeline/quality.py) kiểm tra mặt tối thiểu 80 px, độ sáng
  trung bình 45–230 và phương sai Laplacian tối thiểu 20. Đây là ngưỡng hiện tại,
  chưa chứng minh tối ưu theo camera, kích thước mặt hoặc loại nhiễu.
- [face_templates.py](../backend/app/services/face_templates.py) dùng cùng
  recognizer cho đăng ký và điểm danh. Bản chân dung lưu 400×600 phục vụ hiển
  thị có crop/resize, không bảo đảm giữ toàn bộ pixel nguồn để tái tạo template.
- Profile preprocessing được ghép vào model_version khi enforce. API chỉ ghép
  đủ năm góc cùng phiên bản và không trộn embedding khác profile.

### Những điểm có thể cải thiện

1. Nhiều lần nội suy khi xoay cứu detector, căn mắt và dlib tạo face chip có thể
   làm mờ chi tiết; cần đo lợi ích thực của mỗi lần warp.
2. Dlib đã tự tạo face chip căn chỉnh 150×150 với padding mặc định 0,25 trong
   compute_face_descriptor. Không mặc định bổ sung một lần căn chỉnh ngoài nữa.
   Nguồn: [mã nguồn dlib](https://github.com/davisking/dlib/blob/master/tools/python/src/face_recognition.cpp).
3. CLAHE hiện chạy cả ảnh khi bật, không phân biệt mặt đủ sáng với mặt thiếu
   tương phản. Việc ảnh nhìn rõ hơn không đồng nghĩa embedding chính xác hơn.
4. Tìm nhiều hướng trên toàn khung có thể làm tăng mạnh p95 khi mất mặt.
5. Phương sai Laplacian có thể tăng do nhiễu hoặc sharpening; phải đo ảnh nguồn,
   không dùng ảnh đã tăng cường làm bằng chứng ảnh đủ nét.
6. Chưa có benchmark recognition theo người, phiên, camera và điều kiện sáng
   để quyết định cấu hình tốt nhất.

## 2. Luồng đích

```text
Ảnh camera/upload
  → giải mã và kiểm tra dữ liệu
  → chuẩn hóa hướng ảnh đúng một lần
  → detector + ROI + kiểm tra một mặt
  → đo chất lượng và pose trên pixel nguồn
  → chọn nhánh xử lý theo chất lượng
      ├─ ảnh tốt: giữ nguyên
      ├─ thiếu tương phản nhẹ: gamma HOẶC CLAHE giới hạn
      └─ nhiễu nhẹ: bộ lọc bảo toàn biên khi đã đo có lợi
  → căn chỉnh/crop đúng hợp đồng dlib
  → dlib embedding 128D
  → so khớp mẫu cùng profile
  → xác nhận theo nhiều frame ở worker
  → ghi điểm danh có idempotency
```

Không có liveness, PAD hoặc thử thách quay đầu trong luồng này. Hướng dẫn năm
góc lúc **đăng ký mẫu** vẫn được giữ; nó khác luồng điểm danh thông thường.

## 3. Hợp đồng dữ liệu phải giữ

- Input công khai vẫn là bytes hoặc BGR uint8 H×W×3; không sửa array đầu vào.
- Không ép méo tỷ lệ khuôn mặt. Không đưa ảnh biên, ảnh nhị phân hoặc grayscale
  thay cho ảnh RGB mà dlib đã được huấn luyện để nhận.
- Face box trả về API luôn là xywh theo ảnh nguồn; dùng ma trận đồng nhất 3×3
  để biến đổi và ánh xạ ngược. Kiểm tra clipping, pixel hợp lệ và landmark lỗi.
- Kích thước chip 150×150 là hợp đồng nội bộ dlib; giữ wrapper hiện có trước
  khi cân nhắc adapter nhận chip đã căn chỉnh, không đổi model sang input 112×112.
- Embedding vẫn float32 128D, metric Euclidean. Không thay schema DB,
  AttendanceRecord, template cũ hoặc threshold nhận diện trong lượt nâng cấp này.
- Một hàm chuẩn bị ảnh dùng chung cho enrollment, scan-frame và camera worker.
  Mọi tham số ảnh hưởng embedding phải nằm trong profile mới pre-v2.
- Lỗi tăng cường ảnh có thể quay về nhánh ảnh nguồn **nếu** nguồn đã qua kiểm
  tra chất lượng. Lỗi giải mã, nhiều mặt khi đăng ký, mặt quá nhỏ, che khuất nặng hoặc biến
  đổi không hợp lệ phải trả lý do yêu cầu chụp lại.

## 4. Các thuật toán đề xuất và giới hạn

| Nhóm | Thuật toán và cách áp dụng | Ưu tiên / điều kiện |
|---|---|---|
| Hướng và tỷ lệ | Chuẩn hóa EXIF/cấu hình camera; similarity transform từ landmark; hợp nhất ma trận trước một lần warp | P1. Kiểm tra decoder đã áp EXIF chưa để tránh xoay hai lần. Mirror chỉ theo metadata/cấu hình; CSS selfie không có nghĩa pixel gửi lên bị lật. |
| Landmark | Kiểm tra khoảng cách hai mắt, điểm nằm trong ROI, sai số reprojection; ưu tiên alignment có sẵn của dlib | P1. So sánh dlib nguyên bản với căn roll ngoài; chỉ dùng RANSAC khi đủ điểm, không dùng 2 điểm để suy ra affine đầy đủ. |
| Độ sáng | Gamma bằng LUT với miền tham số giới hạn; CLAHE trên kênh Y hoặc L với clip limit nhỏ | P1. Chạy trên ROI mặt có vùng đệm và theo quality; benchmark từng nhánh, không mặc định chồng gamma + CLAHE. Ảnh cháy/mất chi tiết phải chụp lại. |
| Nhiễu | Median 3×3 cho nhiễu xung; bilateral nhỏ cho nhiễu nhẹ | P2. Ước lượng loại nhiễu trước, tránh lọc ảnh đã sạch; đánh giá mất texture và độ trễ. Không làm mịn da. |
| Chiếu sáng không đều | Single/Multi-Scale Retinex có kiểm soát màu; so sánh với gamma/CLAHE | P3, chỉ thí nghiệm. Có thể gây halo, lệch màu và khác miền huấn luyện dlib. |
| Chuẩn hóa học thuật tham chiếu | Tan–Triggs: gamma, Difference of Gaussians và robust contrast normalization | P3, nhánh benchmark độc lập; kết quả với descriptor cổ điển không chứng minh cải thiện ResNet RGB. Không thay input mặc định. |
| Độ nét | Tenengrad/Sobel kết hợp Laplacian, độ bão hòa và tỷ lệ vùng mặt hợp lệ | P1/P2. Chuẩn hóa đánh giá theo kích thước ROI và camera; không bỏ quality gate vì ảnh sau lọc trông nét. |
| Biên/kết cấu | Kirsch, Sobel, Gabor, LBP phục vụ chẩn đoán hoặc baseline học thuật | Chỉ đo đạc; không thay ảnh màu đưa vào dlib và không gọi đây là liveness. |
| Lens distortion | Hiệu chuẩn camera và undistort có intrinsics đã đo | P3, chỉ khi camera có méo đáng kể. Không dùng bộ thông số camera khác. |
| Chọn frame | Chọn frame đủ chất lượng trong cửa sổ ngắn, ưu tiên pose gần mẫu đăng ký; reset khi đổi người | P2. Mỗi quyết định vẫn phải dựa trên embedding mới, không lấy box/embedding cũ làm kết quả frame mới. |

Nền tảng thuật toán:
[CLAHE/OpenCV](https://docs.opencv.org/4.x/d5/daf/tutorial_py_histogram_equalization.html),
[Affine/OpenCV](https://docs.opencv.org/4.x/d4/d61/tutorial_warp_affine.html),
[Bilateral — Tomasi & Manduchi, ICCV 1998](https://users.soe.ucsc.edu/~manduchi/Papers/ICCV98.pdf),
[Tan & Triggs, TIP 2010](https://doi.org/10.1109/TIP.2010.2042645),
[Retinex — Jobson, Rahman & Woodell, TIP 1997](https://ntrs.nasa.gov/api/citations/19990005051/downloads/19990005051.pdf),
[calibration/pose/OpenCV](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html).

### Phân biệt nghiêng ảnh và quay đầu

Roll trong mặt phẳng ảnh có thể hiệu chỉnh bằng phép quay/similarity. Yaw/pitch
lớn là thay đổi phối cảnh của vật thể 3D, có phần mặt bị che khuất. Một homography
2D không thể khôi phục đúng phần mặt không được camera quan sát. Với trường hợp
này, dùng các mẫu năm góc đã đăng ký hoặc yêu cầu người dùng chỉnh hướng; không
dùng warp mạnh, làm đẹp mặt hoặc sinh chi tiết để tăng score.

## 5. Các bước triển khai và điểm tích hợp

### P0 — Hoàn tất phạm vi hiện tại

- Gỡ module, model loader, thử thách API, trường schema, UI và dependency
  liveness; cấu hình cũ được bỏ qua có chủ đích để ứng dụng vẫn khởi động.
- Giữ nguyên thông số, profile và thuật toán preprocessing hiện hành.
  Chỉ gỡ liveness không làm đổi model_version và không buộc thu lại mẫu.
- Chạy kiểm thử backend, đăng ký, camera worker, giao diện và lint.
- Những bộ dữ liệu PAD đã tải trong storage là dữ liệu cục bộ chưa dùng;
  không huấn luyện tiếp hoặc nạp chúng vào recognition.

Kiểm chứng P0 đã chạy: 78 tests đạt, gồm năm kiểm thử Chrome với webcam tổng
hợp; Ruff và kiểm tra cú pháp JavaScript đạt. Smoke test với cấu hình local
nạp dlib-resnet-v1-128d:pre-v1-986b1750fc, preprocessing=enforce,
supports_pose=True và không nạp ONNX Runtime/PAD. Chưa đo accuracy trên camera
thật; các mục tiêu P1–P3 bên dưới vẫn cần được nghiệm thu trên dữ liệu thực tế.

### P1 — Đo baseline, chuẩn hóa hình học và ánh sáng

1. Lập bộ benchmark nhận diện có đồng ý sử dụng, khởi đầu khoảng 30 người,
   ít nhất ba phiên khác nhau và các camera thực tế. Enrollment và probe phải
   khác phiên; tách nhóm người dùng để chọn tham số và nghiệm thu độc lập.
2. Thử quay 0/90/180/270, roll ±10/±20/±30, gương có cấu hình, ánh sáng
   trước/sau/bên, nhiễu và nén. Dữ liệu biến đổi tổng hợp chỉ kiểm tra kiểm soát,
   không thay cho ảnh camera thật; mọi biến thể cùng ảnh phải ở cùng phân vùng.
3. Thêm metrics chất lượng vào [quality.py](../ai_pipeline/quality.py).
   Phân biệt lỗi không thể cứu với thiếu tương phản nhẹ; giữ nhánh pre-v1 hiện tại.
4. Tại [preprocessing.py](../ai_pipeline/preprocessing.py), thêm options pre-v2
   versioned cho từng thuật toán và hợp nhất geometry. Tại
   [analysis.py](../ai_pipeline/analysis.py), chọn nhánh theo quality; không
   chọn nhánh bằng cách tìm ảnh có điểm match cao nhất trên danh sách sinh viên.
5. Kiểm tra hợp đồng face chip của [recognition.py](../ai_pipeline/recognition.py);
   benchmark có/không căn mắt ngoài. Giữ dlib tự căn chỉnh làm cấu hình đối chứng.
6. So sánh nguyên bản, geometry-only, gamma-only, CLAHE-only, geometry + mỗi
   nhánh ánh sáng. Chỉ đề xuất nhánh có lợi trên dữ liệu nghiệm thu.

### P2 — Giảm nhiễu, chọn frame, vận hành

7. Bổ sung median/bilateral có điều kiện và đo ablation riêng.
8. Đo kích thước ROI phù hợp, giới hạn số hướng tìm detector và cache trạng thái
   camera; luôn chạy phát hiện/nhận diện mới trước khi ghi điểm danh.
9. Thêm hướng dẫn chụp lại có lý do cụ thể vào frontend và desktop, giữ schema
   kết quả nhận diện. Chọn frame tốt hơn thay vì giảm ngưỡng tin cậy.
10. Triển khai shadow có lấy mẫu để tránh nhân đôi chi phí trên mọi frame.
    Chỉ thu metrics tổng hợp và ảnh benchmark đã được phép giữ.

### P3 — Thí nghiệm học thuật nâng cao

11. Đánh giá Retinex và Tan–Triggs ở pipeline riêng; so sánh recognition và
    độ trễ, không chỉ PSNR/SSIM hoặc ảnh minh họa.
12. Hiệu chuẩn/undistort chỉ nếu kiểm tra camera chứng minh có méo đáng kể.
13. Chọn cấu hình nhỏ nhất đạt tiêu chí; không bật mọi bộ lọc chỉ vì có trong tài liệu.

## 6. Đánh giá và tiêu chí nghiệm thu

Các ngưỡng dưới đây là **mục tiêu đề xuất**, không phải kết quả đã đo:

- Báo cáo FAR/FMR và FRR/FNMR, TAR tại FAR cố định, nhận sai danh tính trong
  lớp, tỷ lệ không tìm thấy mặt, tỷ lệ từ chối chất lượng và thời gian điểm danh.
  Ở chế độ tìm trong danh sách lớp, báo thêm tỷ lệ nhận nhầm ở mức giao dịch
  (FPIR) để không nhầm FAR so sánh cặp với rủi ro điểm danh thực tế.
- Điều chỉnh threshold/margin chỉ trên validation. Test chỉ chạy sau khi đóng
  băng cấu hình. Báo khoảng tin cậy theo người/phiên và số giao dịch; không đếm
  hàng trăm frame cùng video như hàng trăm người độc lập.
- Mục tiêu: giảm ít nhất 10% tương đối số lần từ chối sai ở nhóm ảnh khó, trong
  khi tỷ lệ nhận nhầm không xấu hơn baseline ở operating point đã chọn.
  Nếu mẫu chưa đủ chứng minh, kết luận chưa đủ dữ liệu.
- Nhóm ảnh đủ sáng/nhìn thẳng phải giữ chất lượng baseline; mọi suy giảm đáng kể
  cần loại bỏ nhánh hoặc giảm phạm vi áp dụng.
- Đo p50/p95 end-to-end trên CPU hiện tại. Ngân sách ban đầu cho phần tăng thêm
  preprocessing là p95 ≤30 ms và không làm tổng p95 tăng quá 10%; xác nhận lại
  bằng benchmark trước khi cam kết cho sản phẩm.
- Test round-trip tọa độ, input bất biến, dtype/kích thước, clipping, nhiều mặt,
  landmark lỗi, fallback và đồng nhất profile enrollment/attendance.
- Khi rollout pre-v2: thu lại mẫu cùng profile từ ảnh nguồn hợp lệ, hoặc dùng
  lại ảnh gốc nếu thực sự còn. Không tái tạo template từ embedding hay coi
  portrait 400×600 đã crop là ảnh nguồn tương đương.
- Giữ profile cũ trong DB và chuyển cấu hình có kiểm soát. Khi rollback phải
  quay cả pipeline và tập template tương ứng; không trộn vector hai profile.

## 7. Rủi ro và biện pháp

| Rủi ro | Biện pháp |
|---|---|
| CLAHE/Retinex tăng nhiễu hoặc lệch màu | Gating theo quality, giới hạn tham số, ảnh đủ tốt đi nhánh nguyên bản, nghiệm thu bằng embedding. |
| Warp/crop làm đổi hình học khuôn mặt | Similarity thay affine tự do, landmark kiểm chứng, ma trận hợp nhất và vùng pixel hợp lệ. |
| Alignment ngoài chồng alignment dlib | Đo ablation; ưu tiên hợp đồng dlib, không resize/căn hai lần theo hai template khác nhau. |
| Tăng sáng làm ảnh hỏng vượt quality gate | Quality trên pixel gốc; phân loại trường hợp có thể cứu, kiểm tra bão hòa và kích thước trước enhancement. |
| Mẫu cũ và truy vấn mới không tương thích | Profile version trong model_version; đăng ký và quét cùng pipeline; rollback theo cặp cấu hình/template. |
| Tối ưu ảnh đẹp nhưng nhận diện kém | FAR/FRR/FPIR và độ trễ là tiêu chí chính; đánh giá riêng từng điều kiện và từng camera. |
| Giữ ảnh nguồn tạo thêm dữ liệu sinh trắc | Chỉ thêm lưu nguồn nếu có đồng ý và chính sách lưu giữ/xóa; không đưa ảnh hoặc embedding vào Git/log. |

**Bước vận hành tiếp theo:** thu bộ benchmark camera theo giao thức P1, chạy ablation,
chọn profile và thu lại năm góc từ nguồn hợp lệ trước khi chuyển pre-v2 enforce.
