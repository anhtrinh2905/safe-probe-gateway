# ADR 0002 — Guardrail hai lớp, và LLM chỉ được chọn hai định danh

- **Ngày:** 2026-08-10
- **Trạng thái:** Accepted
- **Liên quan:** `src/safe_probe/limits.py`, `src/safe_probe/plan.py`,
  week3 `docs/adr/0002-llm-de-xuat-tool-chung-minh.md`

## Bối cảnh

Tuần 3 kết luận: **LLM đề xuất, tool chứng minh, người ký verdict.** Guardrail
đặt trong code chứ không đặt trong prompt, vì "response của target đi thẳng vào
prompt, nên prompt là thứ có thể bị chính nó thuyết phục".

Tuần 4 giữ nguyên kết luận đó và đẩy nó đi thêm một bước: guardrail không chỉ ra
khỏi prompt, mà ra khỏi cả tiến trình.

## Vấn đề 1 — Hai lớp giới hạn có phải là thừa không?

Tool có rate limit, timeout, giới hạn kích thước. Gateway cũng có. Nhìn qua thì
trùng lặp.

Không trùng, vì hai lớp trả lời hai câu hỏi khác nhau:

| | Tool (`src/safe_probe/limits.py`) | Gateway (`gateway/policy.yml`) |
|---|---|---|
| Trả lời câu hỏi | "tool có cư xử tử tế không?" | "điều gì thực sự được phép?" |
| Khi tool sai | không còn tác dụng | vẫn nguyên vẹn |
| Tắt được không | có, `--no-client-limits` | không |
| Là biên giới an ninh | **không** | **có** |

Con số được đặt sao cho lớp client luôn chạm trước:

| | Tool | Gateway |
|---|---|---|
| Rate | 20/phút | 30/phút |
| Request size | 32 KB | 64 KB |
| Response size | 64 KB | 256 KB |
| Timeout | **8 s** | **5 s** |

Timeout là con số duy nhất đi ngược chiều, và đó là cố ý: tool phải chờ *lâu hơn*
gateway, để một upstream chậm sinh ra `504` **của gateway** thay vì một timeout
phía client — cái sau không nói gì về gateway cả.

`--no-client-limits` tồn tại để chứng minh điều này chứ không phải để tiện: tắt
sạch mọi kiểm soát phía client, gateway vẫn từ chối y hệt. Nếu không có cờ đó,
báo cáo sẽ không phân biệt được lớp nào đang gánh việc.

## Vấn đề 2 — LLM được quyết định cái gì?

`plan.py` cho một LLM đề xuất request. Câu hỏi giống hệt tuần 3 nhưng trong bối
cảnh mới: nếu để model tự viết URL và payload, thì mọi thứ ở trên vô nghĩa — model
đọc response của Juice Shop (một ứng dụng cố tình thù địch) và có thể bị thuyết
phục bởi chính response đó.

**Quyết định: model chỉ được trả về hai định danh, từ hai danh sách đóng.**

```
route_id     phải có trong kết quả GET /_gateway/routes
payload_id   phải có trong payloads.SAFE_PAYLOADS
```

Nó **không** viết URL, **không** đặt header, **không** chọn method, **không** bao
giờ nhìn thấy API key. `_send()` là chỗ duy nhất một URL được tạo ra, và không có
gì từ model đi vào path, method hay header — model chọn một dòng, hàm đó đọc dòng
đó.

Điều xấu nhất một model bị prompt-injection làm được: chọn một route khác trong
allowlist và một payload khác trong catalogue. Tức là một request mà tool vốn đã
sẵn sàng gửi.

Ba lớp kiểm tra, không phải một:

1. `_validate()` từ chối id lạ và **prompt lại model kèm lý do** — không raise, vì
   một model chọn sai id thì nên được sửa chứ không nên làm hỏng cả run.
2. `payloads.get()` chạy lại `check_safe()` tại thời điểm dùng, không tin catalogue.
3. Gateway vẫn có quyền từ chối, kể cả khi hai lớp trên đều nhầm.

## Cái giá phải trả

- **Model không tìm được thứ nằm ngoài catalogue.** Đúng như thiết kế. Nếu muốn
  probe một endpoint mới, người thêm nó vào `policy.yml` — đó là một quyết định
  của người, và nó nằm trong git diff.
- **Vòng thứ hai có đưa response vào context.** Đó là điều làm vòng hai đáng có,
  và cũng là đường prompt-injection duy nhất còn lại. Prompt nói rõ mọi response
  là dữ liệu không tin cậy — nhưng đó là biện pháp yếu, và nó *không phải* thứ đang
  giữ an toàn. Thứ đang giữ an toàn là danh sách đóng.

## Hệ quả

- Thêm khả năng cho model = mở rộng một trong hai danh sách, và phải qua review.
- Không được thêm tham số nào vào `Proposal` mà đi thẳng vào request.
