# AGENTS.md

Hướng dẫn cho AI agent (và người mới) làm việc trong repo này.

## Repo này là gì

Một **API Gateway** đặt trước hai ứng dụng thử nghiệm, và một **Python tool** chỉ
biết đúng một địa chỉ: gateway. Tool gửi request kiểm thử với payload an toàn;
gateway quyết định request nào đi tiếp.

Điểm mấu chốt: **guardrail nằm ngoài tiến trình đang bị kiểm thử.** Tuần 3 đặt
allowlist trong `llm/agent.py::_build_url` — cùng một tiến trình đang đọc response
của target vào prompt. Một agent bị prompt injection có thể tự thuyết phục mình bỏ
qua allowlist của chính nó; nó không sửa được cấu hình của một process khác.

Đừng tối ưu việc "tool gửi được nhiều loại request hơn" mà làm hỏng việc
"gateway là thứ duy nhất quyết định request nào đi tiếp".

## Quy tắc phân chia thư mục

| Thư mục | Chứa gì | Ai đọc | Có được sửa tay không |
|---|---|---|---|
| `gateway/` | Gateway: code + `policy.yml` + Dockerfile | — | Có |
| `targets/` | Ứng dụng thử nghiệm (lab-app) | — | Có |
| `src/safe_probe/` | Python tool: client, limits, payload, audit, lớp LLM | — | Có |
| `scripts/` | Entrypoint bash: up/down/smoke/verify | — | Có |
| `docs/` | **Quá trình**: phương pháp, ADR | Người | Có |
| `data/` | **Output thô**: audit log của tool và của gateway | Máy | **Không** — regenerate |
| `reports/` | **Kết quả**: bằng chứng + bảng suite | Người | Có |
| `tests/` | pytest | — | Có |

Ba nhầm lẫn hay gặp:

1. **Đừng để kết luận trong `data/`.** `data/` do `scripts/up.sh` và tool sinh ra,
   xoá đi chạy lại được. Xoá `data/` không được phép làm mất công sức trí óc nào.
2. **Đừng để quá trình trong `reports/`.** `reports/README.md` trả lời "chứng minh
   được cái gì". "Làm thế nào và vì sao" thuộc về `docs/`.
3. **Đừng để chính sách trong code.** Allowlist, rate limit, timeout, kích thước —
   tất cả nằm trong `gateway/policy.yml`. `gateway/app.py` phải generic.

## Lệnh

```bash
bash scripts/up.sh                    # sinh API key (nếu chưa có) + dựng gateway & target
bash scripts/smoke.sh                 # chứng minh 401/403/404/405/413/429/504 bằng curl
bash scripts/down.sh                  # hạ toàn bộ
bash scripts/verify.sh                # ruff + pytest + grep key + ggshield

PYTHONPATH=src python3 -m safe_probe.cli routes                       # allowlist gateway công bố
PYTHONPATH=src python3 -m safe_probe.cli get /api/Products
PYTHONPATH=src python3 -m safe_probe.cli get /ftp                     # -> blocked
PYTHONPATH=src python3 -m safe_probe.cli post /rest/user/login --payload wrong-type-int
PYTHONPATH=src python3 -m safe_probe.cli suite                        # toàn bộ payload x route
PYTHONPATH=src python3 -m safe_probe.cli plan --goal "input validation"  # LLM đề xuất
```

Bước cuối của `smoke.sh` cố tình làm cạn rate bucket của gateway (45 request
liên tiếp). Chờ ~70 giây trước khi chạy `suite`, nếu không những request đầu sẽ
nhận 429 — đúng như thiết kế, chỉ là không phải thứ đang muốn đo.

## Quy ước code

- Python 3.11+, type hint đầy đủ, `from __future__ import annotations`.
- Comment viết bằng tiếng Anh và giải thích **vì sao**, không mô tả lại code.
- Docs và báo cáo viết bằng tiếng Việt (đối tượng đọc là team).
- `src/safe_probe/` **stdlib-only**. Không `requests`, không `httpx`, không
  `python-dotenv`, không SDK LLM. Tool là thứ đang bị kiểm thử; bề mặt của nó phải
  đọc hết được. FastAPI/httpx/pyyaml chỉ tồn tại bên trong container `gateway/`.

## Việc tuyệt đối không làm

- **Không publish port của target.** `juice-shop` và `lab-app` nằm trên network
  `internal: true`, không có `ports:`. Đây là bằng chứng cho "mọi request đều đi
  qua gateway" — nó là sự thật của topology, không phải quy ước lập trình. Thêm
  `ports:` vào target là phá hỏng toàn bộ luận điểm của repo.
- **Không cho `src/safe_probe/` import `gateway/`.** Hai thành phần này không được
  chia sẻ code. Nếu tool import được policy, guardrail lại quay về trong tiến trình.
- **Không hard-code allowlist trong tool.** Tool lấy danh sách route từ
  `GET /_gateway/routes`. Nó có thể *đoán sai* — và bị gateway từ chối. Đó là điều
  đúng đắn: tool không phải nguồn sự thật về policy.
- **Không thêm payload phá hoại.** `payloads.py` chỉ chứa chuỗi dài, ký tự đặc
  biệt, giá trị rỗng, sai kiểu, biên số học. SQLi / XSS / path traversal / command
  injection / JNDI nằm trong `FORBIDDEN_PATTERNS` và `tests/test_payloads.py` sẽ
  đỏ nếu chúng lọt vào catalogue. Đây là bất biến, không phải lời hứa.
- **Không ghi API key ra bất cứ đâu.** Redaction đặt tại sink
  (`audit.py::AuditLog.write`, quét đệ quy qua `_clean`), không đặt tại chỗ gọi —
  chỗ gọi thì sẽ có chỗ quên, và quên im lặng. `tests/test_redaction.py` chạy
  probe với key sentinel rồi grep file log.
- **Không để LLM tự viết URL.** `plan.py` chỉ được trả về `route_id` có sẵn trong
  policy và `payload_id` có sẵn trong catalogue. Nó không ghép path, không đặt
  header, không bao giờ nhìn thấy API key. Lý do: `docs/adr/0002-guardrail-hai-lop.md`.
- **Không đổi dữ liệu thật trên target.** Allowlist chỉ có endpoint đọc, cộng thêm
  `POST /rest/user/login` (sai credential → 401, không ghi gì) và `POST /echo` của
  lab-app (phản chiếu, không lưu).
