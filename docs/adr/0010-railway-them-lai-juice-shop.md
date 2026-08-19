# ADR 0010 — Railway dùng lại đúng allowlist của local: thêm Juice Shop, bỏ policy rút gọn

- **Ngày:** 2026-08-19
- **Trạng thái:** Accepted — đảo ngược Quyết định 2 của
  [ADR 0005](0005-streamlit-demo-tren-railway.md)
- **Liên quan:** `gateway/policy.railway.yml`, `gateway/policy.py`,
  `ui/streamlit_app.py`, `tests/test_policy.py`, `tests/conftest.py`

## Bối cảnh

ADR 0005 (tuần 4) cố tình bỏ Juice Shop khỏi bản demo Railway để tiết kiệm
compute, chỉ giữ lab-app. Tuần này thêm preset "🔴 Login SQLi" (ADR 0009) --
route `login` chỉ tồn tại trong `policy.yml` (local), nên trên Railway preset
đó luôn nhận `404 blocked-route` thật (không phải lỗi, đúng như policy công
bố) — người xem demo public không thấy được đúng cái ADR 0009 muốn minh hoạ.
Quyết định: chấp nhận trả thêm chi phí, cho Railway dùng **đúng một allowlist**
với local.

## Quyết định 1 — Thêm service `juice-shop` trên Railway, không dựng lại policy từ đầu

Tạo service Railway mới tên chính xác `juice-shop`, image
`bkimminich/juice-shop:latest`, biến môi trường `NODE_ENV=unsafe` -- khớp
từng chữ với service `juice-shop` trong `docker-compose.yml`. Đặt đúng tên
service là bắt buộc: DNS nội bộ Railway là `<service-name>.railway.internal`,
nên tên sai sẽ làm `gateway` không resolve được host.

## Quyết định 2 — `policy.railway.yml` giờ liệt kê đúng 9 route như `policy.yml`, chỉ khác hostname

Trước: `policy.railway.yml` chỉ có 4 route lab-app. Giờ: cả 9 route
(products-search, products, app-version, login, metrics + echo, slow, big,
status) -- copy nguyên `routes:` của `policy.yml`, chỉ đổi `upstreams:` sang
`http://juice-shop.railway.internal:3000` / `http://lab-app.railway.internal:8080`
thay vì hostname kiểu Docker Compose (`juice-shop:3000`, `lab-app:8080`).

`tests/test_policy.py::test_railway_policy_declares_the_same_routes_as_local`
so sánh `{(id, upstream, methods)}` của hai file bằng tập hợp -- không phải
đọc comment rồi tin, mà là một bất biến kiểm được: hai file **không được**
lệch route nào kể từ giờ, chỉ được lệch hostname. Nếu ai thêm route mới vào
`policy.yml` mà quên `policy.railway.yml`, test này đỏ.

## Quyết định 3 — Cột "target" trên trang Allowlist, để phân biệt lab-app/juice-shop

`GET /_gateway/routes` trước đây không nói route nào thuộc backend nào --
`policy.py::Route.public()` giờ thêm field `upstream` (tên trong policy:
`"lab"`/`"juice-shop"`, không phải `upstream_url` -- người xem biết route
thuộc backend nào mà không học thêm một hostname họ không gọi thẳng được,
đúng luận điểm topology của ADR 0003). `render_allowlist_tab` map
`"lab"` → hiển thị `"lab-app"` cho khớp tên service thật, `"juice-shop"` giữ
nguyên.

## Cái giá phải trả

- **Chi phí Railway tăng thật, liên tục** -- đúng cái ADR 0005 từng tránh.
  Chấp nhận vì mục tiêu đổi là: preset minh hoạ prompt injection/SQLi trong
  ADR 0009 giờ demo được công khai, không chỉ ở local.
- **Nhánh 403 forbidden-group giờ demo được trên Railway** (route `metrics`
  quay lại) -- đây là hệ quả tốt của Quyết định 2, không phải mục tiêu chính,
  nhưng đóng luôn khoảng trống ADR 0005 từng ghi nhận ("bản Railway thiếu
  nhánh 403").
- **Hai file policy vẫn phải sửa tay song song** khi thêm route mới -- chấp
  nhận (giống ADR 0005 đã chấp nhận từ đầu), nhưng giờ có test chặn lệch,
  không chỉ dựa vào kỷ luật review.

## Hệ quả

- Thêm route mới: sửa `policy.yml` **và** `policy.railway.yml` (route giống
  hệt, chỉ hostname khác) -- `test_railway_policy_declares_the_same_routes_as_local`
  sẽ đỏ nếu quên.
- Muốn Railway lại rẻ hơn (bỏ Juice Shop lần nữa): xoá service `juice-shop`
  trên Railway, revert `policy.railway.yml` về bản 4-route -- đảo ngược ADR
  này thì cần một ADR mới, không sửa ADR này hay ADR 0005.
