# ADR 0001 — Gateway tự viết thay vì Kong hoặc Nginx

- **Ngày:** 2026-08-10
- **Trạng thái:** Accepted
- **Liên quan:** `gateway/app.py`, `gateway/policy.yml`, [ADR 0003](0003-topology-la-bang-chung.md)

## Bối cảnh

Đề bài cho phép Kong, Nginx, hoặc "một gateway đơn giản". Ba lựa chọn này khác
nhau ở chỗ nào là thứ đáng cân nhắc trước.

| | Kong DB-less | Nginx | Tự viết (FastAPI) |
|---|---|---|---|
| API key | plugin `key-auth` | `map` + `if` | ~10 dòng |
| Rate limit | plugin `rate-limiting` | `limit_req_zone` | token bucket ~25 dòng |
| Allowlist | `routes` khai báo | `location` + default deny | policy YAML |
| Giới hạn request size | plugin `request-size-limiting` | `client_max_body_size` | check `Content-Length` |
| **Giới hạn response size** | **không có plugin OSS** | rất khó | ~8 dòng khi stream |
| Image | ~200 MB | ~50 MB | ~120 MB |
| Guardrail nằm ở đâu | tiến trình riêng | tiến trình riêng | tiến trình riêng |

## Vấn đề

Lo ngại chính khi tự viết: **liệu có mất đi luận điểm của bài không?** Tuần 3 đã
đặt allowlist trong `llm/agent.py::_build_url` — cùng tiến trình với thứ đang đọc
response của target vào prompt. Nếu tuần 4 chỉ chuyển allowlist sang một module
Python khác trong cùng repo, thì không chứng minh thêm được gì.

Nhưng "tự viết" không đồng nghĩa với "cùng tiến trình". Ba ràng buộc dưới đây giữ
nguyên tính chất *ngoài tiến trình* của guardrail, và chúng là lý do lựa chọn này
chấp nhận được:

1. Gateway chạy trong container riêng, dependency riêng (`gateway/requirements.txt`).
2. `src/safe_probe/` **không được import** `gateway/` — quy tắc ghi trong AGENTS.md.
3. Target không publish port; chỉ gateway publish. Xem ADR 0003 — đây mới là ràng
   buộc thật sự, và nó không phụ thuộc vào việc gateway được viết bằng gì.

## Quyết định

Tự viết gateway bằng FastAPI + httpx, chính sách nằm trong `gateway/policy.yml`.

Lý do quyết định, theo thứ tự quan trọng:

**1. Giới hạn kích thước response.** Đề bài yêu cầu giới hạn "kích thước
response". Kong OSS không có plugin nào làm việc này (`request-size-limiting` chỉ
lo chiều đi; `response-ratelimiting` là quota theo header, không phải byte).
Nginx cũng không có cách sạch sẽ để cắt body giữa chừng. Với gateway tự viết, đó
là 8 dòng trong vòng lặp `aiter_bytes`:

```python
room = limits.max_response_bytes - total
if len(chunk) >= room:
    chunks.append(chunk[:room]); truncated = True; break
```

Nếu chọn Kong, mục này sẽ phải ghi trong báo cáo là "làm ở client" — tức là
không có ai thực thi cả, vì client chính là thứ đang bị kiểm thử.

**2. Mã lỗi nói đúng điều mình muốn nói.** Endpoint ngoài allowlist trả `404`
chứ không phải `403`, vì `403` cho người gọi biết endpoint đó tồn tại. Header
`X-Gateway-Decision` có mặt trên **mọi** phản hồi, nên tool phân biệt được
"gateway chặn" với "ứng dụng trả 404". Với Kong, thứ tự plugin và nội dung phản
hồi là thứ phải uốn theo, không phải thứ mình đặt ra.

**3. Chính sách đọc được trong một phút.** `policy.yml` dài 100 dòng và toàn bộ
là *quyết định*: cho phép cái gì, ai được gọi, giới hạn bao nhiêu. `kong.yml`
tương đương sẽ trộn lẫn quyết định với cấu hình plugin.

## Cái giá phải trả

- **Bề mặt tấn công là code của mình.** Kong đã được nhiều người soi; `app.py`
  thì chưa. Bù lại bằng `tests/test_policy.py` (25 test cho riêng loader) và bằng
  việc file này ngắn.
- **Không có HA, không có cluster, không có plugin ecosystem.** Không cần cho bài
  tập; sẽ cần nếu đưa ra production. Nếu đến lúc đó, `policy.yml` dịch sang
  `kong.yml` gần như một-một — đó là lý do chính sách được tách khỏi code.
- **Rate limit chỉ đúng với một worker.** `Dockerfile` hard-code `--workers 1`,
  và có comment giải thích. Hai worker sẽ âm thầm nhân đôi giới hạn thật.

## Hệ quả

- Mọi thay đổi chính sách là sửa `policy.yml` + restart, không build lại image
  (file được bind-mount).
- Thêm bất kỳ `if path == ...` nào vào `app.py` là dấu hiệu chính sách đang rò rỉ
  vào code — phải chuyển sang YAML.
