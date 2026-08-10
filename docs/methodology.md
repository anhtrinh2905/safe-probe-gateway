# Phương pháp

Tài liệu này trả lời "làm thế nào và vì sao". Kết quả nằm ở
[`reports/README.md`](../reports/README.md).

---

## 1. Câu hỏi mà tuần 4 thực sự trả lời

Đề bài nghe như một bài tập hạ tầng: dựng gateway, viết tool, đặt vài giới hạn.
Nhưng câu hỏi bên dưới nó là câu hỏi tuần 3 để lại:

> Một agent đọc response của target vào prompt của chính nó, rồi tự quyết định
> request tiếp theo. Cái gì ngăn nó đi quá giới hạn?

Tuần 3 trả lời: một hàm trong code của agent (`_build_url`). Câu trả lời đó đúng
nhưng yếu, và tuần 3 đã ghi rõ tại sao — nó nằm cùng tiến trình với thứ đang bị
thuyết phục.

Tuần 4 trả lời: **một tiến trình khác, và một topology mà tiến trình kia không
có cách nào đi vòng.**

Mọi lựa chọn trong repo này đều rơi ra từ đó.

---

## 2. Bốn lớp, xếp từ yếu tới mạnh

| Lớp | Ai thực thi | Tắt được không | Chống được gì |
|---|---|---|---|
| Prompt ("chỉ gửi payload an toàn") | model | model tự tắt | gần như không gì |
| Danh sách đóng trong `plan.py` | code tool | sửa code là xong | model bị injection |
| Giới hạn client (`limits.py`) | code tool | `--no-client-limits` | tool cấu hình sai |
| **Policy gateway** | tiến trình khác | không | tool bị sửa, bị inject |
| **Topology** | Docker | không, trừ khi sửa compose | mọi thứ ở trên cùng lúc |

Lớp trên cùng có mặt vì nó rẻ và giúp model làm việc tốt hơn. Nó **không** được
tính là kiểm soát an ninh, và tài liệu không được nói ngược lại.

Hai lớp dưới cùng là thứ báo cáo dựa vào.

---

## 3. Vì sao endpoint ngoài allowlist trả 404 chứ không phải 403

`403` nói: "cái này tồn tại, bạn không được vào." Với một người gọi đã ở ngoài
allowlist, đó là thông tin miễn phí — họ dùng gateway để vẽ bản đồ thứ nằm sau nó.

`404` không nói gì cả.

`403` vẫn được dùng, nhưng cho trường hợp khác: người gọi **đã biết** route tồn
tại vì nó có trong `GET /_gateway/routes`, chỉ là không thuộc group cần thiết
(`/metrics`). Lúc đó giấu đi cũng vô nghĩa.

Trật tự kiểm tra trong `gateway/app.py` được viết theo đúng logic này:

| # | Chặng | Mã | Vì sao ở vị trí này |
|---|---|---|---|
| 1 | Kích thước request | 413 | Trước khi đọc body — body quá lớn không bao giờ được buffer |
| 2 | API key | 401 | Người lạ không học được gì thêm |
| 3 | Allowlist | 404 | Không tiết lộ cái gì tồn tại |
| 4 | Method | 405 | Chỉ khi đã biết path nằm trong allowlist |
| 5 | ACL group | 403 | Người gọi đã biết, route đã biết |
| 6 | Rate limit | 429 | Kèm `Retry-After` |
| 7 | Proxy | 504 / 502 | |
| 8 | Cắt response | — | Cắt lúc stream, không giữ nguyên body trong RAM |

Mọi phản hồi đều mang header `X-Gateway-Decision`. Không có nó, tool không phân
biệt được "gateway chặn" với "ứng dụng trả 404" — và một run không phân biệt được
hai thứ đó thì không chứng minh được gì.

---

## 4. Tool học allowlist thay vì mang theo allowlist

`ProbeClient.routes()` gọi `GET /_gateway/routes`. Tool **không** giữ bản sao
nào của policy.

Hệ quả có chủ đích: tool có thể *đoán sai*. Nó gửi `/ftp`, và nó nhận 404. Đó là
cách đúng để phát hiện ra rằng route đó không tồn tại — chứ không phải tự kiểm
tra trước bằng một danh sách mà chính nó giữ. Một danh sách do tool giữ sẽ lệch
khỏi gateway sớm hay muộn, và lúc đó tool sẽ báo cáo dựa trên bản sao đã cũ.

---

## 5. Vì sao timeout của tool *lớn hơn* của gateway

Mọi giới hạn phía client đều thấp hơn giới hạn gateway, trừ timeout:

| | Tool | Gateway |
|---|---|---|
| Rate | 20/phút | 30/phút |
| Request size | 32 KB | 64 KB |
| Response size | 64 KB | 256 KB |
| Timeout | **8 s** | **5 s** |

Nếu tool chờ 3 s còn gateway chờ 5 s, thì một upstream chậm luôn sinh ra timeout
phía client — và kết quả đó không nói gì về gateway. Đảo lại: tool chờ 8 s,
gateway bỏ cuộc ở 5 s, và cái quan sát được là `504` **của gateway**, kèm
`X-Gateway-Decision: upstream-timeout`.

Nguyên tắc chung: **giới hạn nào muốn chứng minh thì phải để nó chạm trước.**

---

## 6. Ba thứ được biến từ lời hứa thành test

| Lời hứa | Cách nó thành bất biến |
|---|---|
| "Chỉ payload an toàn" | `FORBIDDEN_PATTERNS` quét ngược catalogue; **và** mỗi pattern phải bắt được một chuỗi tấn công thật (`KNOWN_BAD`) — một regex không khớp gì vẫn làm test đầu xanh mà không bảo vệ gì |
| "Log không lưu API key" | Chạy probe với key sentinel qua đủ mọi đường (header, query, body phản chiếu, field lạ), rồi grep file log |
| "Không đổi dữ liệu thật" | `test_no_route_can_write_real_data` khẳng định mọi route có method khác GET/HEAD đều nằm trong hai ngoại lệ đã ghi |

Hai lỗi thật mà chính các test này tìm ra, không phải do đọc code:

- `Payload.as_text` dùng `repr()`, nên chuỗi CRLF header-injection biến thành hai
  ký tự `\` và `r` và lọt qua pattern `[\r\n]`.
- `SECRET_SHAPED` bắt buộc có `:` hoặc `=` giữa từ khoá và giá trị, nên
  `Authorization: Bearer <token>` — cách credential xuất hiện phổ biến nhất trong
  log — không khớp.

Chi tiết: [ADR 0004](adr/0004-payload-an-toan-la-bat-bien.md).

---

## 7. Redaction đặt ở sink, không đặt ở chỗ gọi

`AuditLog.write` là hàm duy nhất mở file log, và nó quét đệ quy toàn bộ record —
kể cả field mà không ai dự đoán trước.

Lý do: một chỗ gọi phải *nhớ* redact là một chỗ gọi sẽ *quên*, và cái quên đó im
lặng. Log trông vẫn bình thường cho tới lúc có người grep. Với cách này, thêm một
field mới vào `ProbeResult` không cần ai sửa `audit.py`, và
`test_a_field_added_later_is_covered_without_anyone_updating_the_scrubber` giữ
cho điều đó đúng.

Ba lớp redaction:

1. **Theo tên header** — `x-api-key`, `authorization`, `cookie` bị thay bằng
   `***REDACTED***` bất kể giá trị.
2. **Theo giá trị đã biết** — key thật bị thay ở mọi chuỗi, kể cả trong body mà
   ứng dụng phản chiếu lại.
3. **Theo hình dạng** — `SECRET_SHAPED` bắt thứ trông giống credential mà repo
   này chưa từng biết (token do ứng dụng sinh ra).

Gateway có bản redaction riêng của nó, không dùng chung code với tool. Trùng lặp
này là cố ý: hai thành phần không được chia sẻ code, nếu không thì
`src/safe_probe/` sẽ import được `gateway/`.

---

## 8. Cách chạy lại toàn bộ

```bash
bash scripts/up.sh        # sinh API key, dựng gateway + 2 target, tự kiểm tra topology
bash scripts/smoke.sh     # 14 kiểm tra bằng curl -> reports/evidence/
                          # (lưu ý: bước cuối cố tình làm cạn rate bucket)
sleep 70                  # chờ bucket đầy lại trước khi chạy suite
PYTHONPATH=src python3 -m safe_probe.cli suite    # 72 request, ~4 phút
bash scripts/verify.sh    # ruff + pytest + grep key + ggshield
```

Lớp LLM là tuỳ chọn và cần `OPENCODE_API_KEY` trong `.env`:

```bash
PYTHONPATH=src python3 -m safe_probe.cli plan --goal "input validation" --rounds 2
```

---

## 9. Cái repo này *không* chứng minh

Ghi ra để báo cáo không bị đọc quá lên:

- **Không chứng minh gateway an toàn.** `app.py` là code tự viết, chưa ai audit.
  Nó chứng minh *policy được thực thi ở đâu*, không chứng minh phần thực thi đó
  không có lỗ hổng.
- **Không chứng minh payload catalogue là đủ.** 22 payload không bao phủ hết các
  cách một ứng dụng xử lý input sai.
- **Không chứng minh lớp LLM an toàn trước injection.** Nó chứng minh *nếu* bị
  injection thì thiệt hại bị chặn ở việc chọn nhầm một dòng trong hai danh sách
  đóng.
- **Không thay thế bước verify của tuần 3.** Một payload an toàn làm endpoint trả
  500 là một *quan sát*, chưa phải một finding cho tới khi có người kết luận nó
  nghĩa là gì.
