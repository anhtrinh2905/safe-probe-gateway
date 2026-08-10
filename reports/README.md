# Kết quả — Tuần 4: API Gateway và kiểm thử request an toàn

Tài liệu này trả lời "chứng minh được cái gì". "Làm thế nào và vì sao" nằm ở
[`docs/methodology.md`](../docs/methodology.md).

Ngày chạy: **2026-08-10** · Sinh bởi `scripts/smoke.sh` và `probe suite`.

---

## 1. Bảng bàn giao

Mỗi dòng là một yêu cầu của đề bài và file chứng minh nó.

| Yêu cầu | Bằng chứng | Kết quả |
|---|---|---|
| API Gateway hoạt động | `evidence/02-allowed-200.txt` | `200`, header `X-Gateway-Route: products` |
| **Request đều đi qua gateway** | `evidence/01-no-direct-access.txt` | `localhost:3000` và `:8080` đều **Connection refused**; `NetworkSettings.Ports` rỗng |
| Endpoint bị cấm bị chặn | `evidence/03-blocked-ftp.txt`, `04-blocked-basket.txt`, `05-blocked-users.txt` | `404` + `X-Gateway-Decision: blocked-route` |
| API key riêng cho công cụ | `evidence/06-no-key-401.txt`, `07-wrong-key-401.txt` | `401` cả hai |
| Chỉ endpoint trong allowlist | `evidence/08-method-405.txt`, `09-forbidden-403.txt` | `405` sai method, `403` sai group |
| Giới hạn request/phút | `evidence/13-rate-limit-429.txt` | 45 request → **29× 200, 16× 429**, kèm `Retry-After: 2` |
| Giới hạn thời gian chờ | `evidence/11-upstream-timeout-504.txt` | `504` sau 5s trên `/slow?ms=9000` |
| Giới hạn kích thước request | `evidence/10-request-413.txt` | body 128 KB → `413` (cap 64 KB) |
| Giới hạn kích thước response | `evidence/12-response-truncated.txt` | upstream trả 500 KB → nhận đúng **262 144 B** |
| Tool xử lý timeout & lỗi kết nối | `tests/test_client.py` | `timeout` / `connection_error` là *outcome*, không phải exception |
| Chỉ dùng payload an toàn | `suite-results.md`, `tests/test_payloads.py` | 22 payload, 11 lớp bị cấm, 112 test |
| **Nhật ký không lưu API key** | `evidence/14-gateway-log-clean.txt`, `tests/test_redaction.py` | grep key trong `data/` → không có |
| Agent đề xuất & gửi request | `evidence/17-llm-plan-run.json` | 12 probe do LLM đề xuất, **0 bị từ chối** |

**`scripts/smoke.sh`: 14 pass / 0 fail.** Toàn bộ chạy bằng `curl`, không qua
Python tool — vì tool có giới hạn riêng, nên một `429` nhìn thấy qua tool không
chứng minh gì về gateway.

---

## 2. Hai endpoint tuần 3 khai thác được, nay không tới được

Tuần 3 tìm ra 8 lỗ hổng khai thác được; hai trong số đó cả ZAP lẫn sqlmap đều bỏ
sót và phải tìm bằng tay. Tuần 4 đặt đúng hai endpoint đó ngoài allowlist.

| Tuần 3 | Endpoint | Tuần 4 |
|---|---|---|
| TP-4 · directory listing | `GET /ftp` | `404 blocked-route` |
| TP-5 · broken access control (IDOR) | `GET /rest/basket/{id}` | `404 blocked-route` |

Không phải vì tool từ chối gửi — tool **có** gửi. Gateway trả lời `404`.

```
$ probe --no-client-limits get /ftp
block GET  /ftp                    404 blocked        65B    10ms
      gateway decision: blocked-route
```

`--no-client-limits` tắt sạch mọi kiểm soát phía client. Kết quả không đổi. Đây
là cách phân biệt lớp nào đang gánh việc — `evidence/16-no-client-limits-still-blocked.txt`.

---

## 3. Quan sát: payload an toàn vẫn lộ ra lỗi xử lý input

Payload `special-quotes` là đúng hai ký tự: `"` và `'`. Không `OR`, không `UNION`,
không comment SQL, không dấu chấm phẩy. Nó vượt qua toàn bộ 11 pattern trong
`FORBIDDEN_PATTERNS`.

Kết quả trên `GET /rest/products/search?q=`:

```
HTTP 500
<title>Error: SQLITE_ERROR: unrecognized token: ""'%') AND deletedAt IS NULL) ORDER BY name"</title>
```

Câu SQL nguyên văn nằm trong thẻ `<title>` của trang lỗi. `POST /rest/user/login`
cũng trả `500` với cùng payload.

**Ý nghĩa.** Tuần 3 đã kết luận endpoint này có SQL injection và đã chứng minh
bằng khai thác thật. Điều tuần 4 thêm vào là một điểm về *phương pháp*: cùng một
lớp lỗ hổng **phát hiện được bằng payload không hề mang tính khai thác**. Hai ký
tự nháy đủ để thấy input chưa qua kiểm tra đã đi thẳng tới lớp SQL, cộng thêm một
lỗi information disclosure (câu truy vấn lộ ra trong trang lỗi).

Đây vẫn là một *quan sát*, chưa phải finding — nó cần một người kết luận nó nghĩa
là gì, đúng như quy trình tuần 3. `evidence/15-safe-payload-500.txt`.

---

## 4. Bảng suite

`probe suite` gửi toàn bộ catalogue payload tới toàn bộ allowlist. Bảng đầy đủ:
[`suite-results.md`](suite-results.md). Dữ liệu máy: `data/probe/suite.json`.

Phân bố outcome:

| Outcome | Số lượng | Nghĩa là gì |
|---|---|---|
| `ok` | 46 | 2xx từ ứng dụng |
| `upstream_client_error` | 22 | 4xx từ ứng dụng — phần lớn là `401` của `/rest/user/login` với credential sai kiểu |
| `upstream_server_error` | 2 | **cả hai đều là `special-quotes`** (mục 3) |
| `forbidden` | 1 | `/metrics` — gateway chặn vì thiếu group `admin` |
| `upstream_timeout` | 1 | `/slow?ms=9000` — gateway bỏ cuộc ở 5s |

Điều đáng chú ý ở cột `answered_by`: mọi dòng đều là `upstream` hoặc `gateway`,
không có `unknown`. Tức là mọi phản hồi đều mang `X-Gateway-Decision`, và tool
luôn biết ai đã trả lời.

Juice Shop chấp nhận gần như mọi thứ mà không lỗi — chuỗi 10 KB, emoji, chữ
Ả Rập, `null`, số nguyên nơi cần email — và trả `401` bình thường. Đó là kết quả
tốt cho ứng dụng ở mọi payload trừ hai ký tự nháy.

---

## 5. Lớp LLM: model đề xuất, gateway quyết định

`probe plan --goal "input validation" --rounds 2`, model `deepseek-v4-pro`.

| | |
|---|---|
| Probe được đề xuất và gửi | **12** |
| Bị từ chối trước khi gửi (id không hợp lệ) | **0** |
| Route model chạm tới | `products-search`, `login`, `echo`, `slow`, `big` |
| Route ngoài allowlist mà model chạm tới | **0 — không có cách nào** |

Model chỉ trả về hai định danh (`route_id`, `payload_id`) từ hai danh sách đóng.
Nó không viết URL, không đặt header, không chọn method, không bao giờ nhìn thấy
API key. Điều xấu nhất một model bị prompt-injection làm được là chọn một dòng
khác trong hai danh sách đó — tức là một request mà tool vốn đã sẵn sàng gửi.

Trích một đề xuất, cho thấy nó đang suy nghĩ về *validation* chứ không về khai thác:

> `login` + `wrong-type-object` — *"Check if the login endpoint gracefully handles
> an object payload instead of a string, possibly causing a server error or
> invalid-credentials response."* → `401`

`evidence/17-llm-plan-run.json`. Lý do thiết kế: [ADR 0002](../docs/adr/0002-guardrail-hai-lop.md).

---

## 6. Danh mục bằng chứng

| File | Chứng minh |
|---|---|
| `01-no-direct-access.txt` | Target không có port ra host |
| `02-allowed-200.txt` | Đường đi hợp lệ hoạt động |
| `03-blocked-ftp.txt` | `/ftp` (tuần 3 TP-4) bị chặn |
| `04-blocked-basket.txt` | `/rest/basket/1` (tuần 3 TP-5) bị chặn |
| `05-blocked-users.txt` | `/api/Users` bị chặn |
| `06-no-key-401.txt` | Không key → 401 |
| `07-wrong-key-401.txt` | Sai key → 401 |
| `08-method-405.txt` | Sai method → 405 |
| `09-forbidden-403.txt` | Thiếu ACL group → 403 |
| `10-request-413.txt` | Request 128 KB → 413 |
| `11-upstream-timeout-504.txt` | Upstream chậm → 504 |
| `12-response-truncated.txt` | Response 500 KB → nhận 262 144 B |
| `13-rate-limit-429.txt` | 45 request → 16 lần 429 + `Retry-After` |
| `14-gateway-log-clean.txt` | Audit log của gateway không chứa key |
| `15-safe-payload-500.txt` | Payload an toàn làm lộ lỗi SQL |
| `16-no-client-limits-still-blocked.txt` | Tắt kiểm soát client, gateway vẫn chặn |
| `17-llm-plan-run.json` | Run của lớp LLM |

---

## 7. Cái báo cáo này *không* khẳng định

- **Không khẳng định gateway an toàn.** `gateway/app.py` là code tự viết, chưa ai
  audit. Nó chứng minh policy được thực thi *ở đâu*, không chứng minh phần thực
  thi đó không có lỗ hổng.
- **Không khẳng định catalogue payload là đủ.** 22 payload không bao phủ hết các
  cách một ứng dụng xử lý input sai.
- **Không khẳng định lớp LLM miễn nhiễm prompt injection.** Nó khẳng định *nếu*
  bị injection thì thiệt hại bị chặn ở việc chọn nhầm một dòng trong danh sách đóng.
- **Không thay thế bước verify của tuần 3.** Mục 3 là quan sát, không phải verdict.
