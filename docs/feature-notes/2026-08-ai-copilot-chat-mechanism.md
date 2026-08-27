# AI SEO Copilot Chat: Cơ chế hoạt động

**Trạng thái:** hoàn thành phần chat đọc dữ liệu đã lưu (stored-data agent).

Copilot không nhận một bản dump toàn bộ database để trả lời theo kiểu tĩnh.
Đây là một agent có tool-calling: model chỉ lấy đúng dữ liệu cần thiết thông
qua các tool read-only, rồi tổng hợp câu trả lời dựa trên kết quả đó.

## Luồng từ lúc người dùng gửi câu hỏi

```text
Người dùng gửi câu hỏi trong Project → Overview
  -> POST /project/<id>/copilot/messages
  -> kiểm tra đăng nhập + quyền vào project
  -> lưu conversation, user message và CopilotRun(pending)
  -> trả HTTP 202 ngay cho trình duyệt
  -> audit worker claim run và chuyển sang running
  -> OpenRouter model chọn tool cần dùng
  -> tool đọc dữ liệu đã lưu của đúng project trong PostgreSQL
  -> model tổng hợp câu trả lời cuối
  -> lưu assistant message, citations và audit trail tool calls
  -> UI poll trạng thái, hiển thị câu trả lời và dừng poll
```

### 1. Browser và Flask route

UI gửi JSON chứa `message` và (nếu đã có) `conversation_id`. Backend chỉ nhận
tin nhắn dài từ 1 đến 4.000 ký tự, kiểm tra quyền project trước khi tạo dữ liệu.
Nếu conversation chưa tồn tại, hệ thống tạo một conversation mới; nếu đã có một
run `pending` hoặc `running` trong conversation, câu hỏi mới bị từ chối tạm thời
để không tạo hai agent cùng trả lời một ngữ cảnh.

Request không chờ model trả lời. Nó lưu `CopilotMessage` cho câu hỏi của người
dùng, tạo `CopilotRun` ở trạng thái `pending`, rồi trả `202 Accepted`. Giao diện
khóa composer trong lúc run đang hoạt động và chỉ poll lại trạng thái mỗi 1,5
giây trong thời gian đó.

### 2. Queue và worker

`audit_worker` là consumer của cả audit queue và Copilot queue. Audit job được
claim trước; chỉ khi không có audit job chờ thì worker mới claim Copilot run.
Điều này bảo đảm chat không làm gián đoạn crawl/audit đã được đặt lịch, đổi lại
chat có thể đợi nếu queue audit đang bận.

Khi claim run, PostgreSQL row lock với `skip_locked` được dùng để hai worker
không thể xử lý cùng một run. Run được chuyển từ `pending` sang `running` và
được lưu thời gian bắt đầu.

### 3. Agent reasoning loop

Agent lấy AI settings có hiệu lực của project, thêm system prompt an toàn và tối
đa 12 tin nhắn user/assistant gần nhất. Sau đó nó gọi OpenRouter với:

- model đã cấu hình cho project;
- `tool_choice: auto` để model tự chọn tool;
- `temperature: 0.2` để câu trả lời ổn định hơn;
- tool calls được worker thực thi tuần tự; request không ép
  `parallel_tool_calls: false` vì không phải endpoint OpenRouter nào cũng hỗ
  trợ tham số tùy chọn này;
- tối đa 4 vòng reasoning và 6 tool calls cho một câu hỏi.

Model được hướng dẫn phải dùng tool khi cần fact, không được bịa số liệu, không
được tuyên bố đã refresh live data, và phải nêu rõ khi dữ liệu bị thiếu. Sau mỗi
tool call, kết quả có kích thước giới hạn được gửi lại cho model. Model có thể
gọi tool khác hoặc viết câu trả lời cuối. Nếu vượt giới hạn, provider lỗi hoặc
tool lỗi, run được đánh dấu `failed` thay vì làm hỏng worker.

## Tool layer và nguồn dữ liệu

Mọi tool đều đọc dữ liệu đã lưu trong database của project hiện tại. Không tool
nào gọi GA4, GSC, DataForSEO, LibreCrawl hoặc bắt đầu audit mới.

| Tool | Dữ liệu đọc | Ghi chú |
| --- | --- | --- |
| `get_ga4_data` | `ga4_daily_metrics` | Sessions và users, theo khoảng 7–90 ngày |
| `get_gsc_data` | `gsc_daily_metrics` | Clicks, impressions, CTR và position, theo khoảng 7–90 ngày |
| `get_rankings` | Project keyword rankings + history | Có movement, không lẫn competitor rows |
| `get_backlinks` | `backlink_history` từ audit snapshots | Backlink/referring-domain theo snapshot |
| `get_crawl_issues` | Crawl issues của snapshot crawl mới nhất | Có thể lọc issue type |
| `get_competitor_data` | Competitor insights đã lưu | Chỉ dữ liệu competitor thuộc project |
| `get_project_health` | Health Score v2 đã persist | Bao gồm components và confidence |

Ví dụ, với câu hỏi “Traffic giảm vì sao?”, model thường sẽ đọc GA4 và GSC
trước, rồi có thể đọc rankings, Health Score hoặc crawl issues nếu cần bằng
chứng bổ sung. Việc chọn tool do model thực hiện, nhưng dữ liệu trả về và phạm
vi project luôn do server kiểm soát.

## Boundary bảo mật và kiểm soát chi phí

- Flask kiểm tra đăng nhập và quyền project ở tất cả endpoint chat.
- Non-admin chỉ đọc conversation/run do chính họ tạo; admin đọc conversation
  gần nhất của project.
- Model không được phép truyền `client_id` hay chọn project. Server inject
  `ToolContext(client_id, user_id, run_id)` vào tool handler.
- Tool schemas không nhận field lạ; date range bị giới hạn tối đa 90 ngày và
  list result tối đa 100 dòng.
- Tool output được coi là dữ liệu, không phải instruction từ người dùng, nhằm
  giảm rủi ro prompt injection từ dữ liệu crawl/SEO.
- Mỗi lần gọi tool đều lưu `CopilotToolInvocation`: tool name, arguments,
  trạng thái, duration, metadata và lỗi nếu có.
- Lượt gọi OpenRouter là chi phí AI duy nhất của chat hiện tại. Không có chi
  phí API provider SEO mới phát sinh chỉ vì người dùng chat.

## Kết quả được lưu và hiển thị

Các bảng bền vững của tính năng là:

- `copilot_conversations`: một chat thread theo project;
- `copilot_messages`: câu hỏi, câu trả lời và citations;
- `copilot_runs`: trạng thái xử lý, model, thời gian và lỗi;
- `copilot_tool_invocations`: audit trail cho mọi tool call.

Khi model hoàn tất, assistant message và citations được persist. UI hiển thị
citations dạng source chip, ví dụ `Snapshot #56` hoặc `Daily metrics`. Các chip
này chỉ giải thích nguồn đã đọc; chúng không có nghĩa là hệ thống vừa gọi API
hoặc chạy audit mới.

Conversation được lưu để người dùng refresh trang vẫn thấy lịch sử, nhưng model
chỉ nhận 12 tin nhắn gần nhất mỗi run để kiểm soát token và chi phí. Historical
AI Context của Week 4 nên thêm summary/retrieval cho lịch sử dài hạn thay vì
gửi toàn bộ chat vào prompt.

## Chiến thuật tải lịch sử chat

Chat không tải toàn bộ lịch sử conversation khi mở trang hoặc khi AI đang trả
lời. API state dùng message `id` làm cursor ổn định, thay vì offset:

- Lần mở đầu lấy **30 message mới nhất** và trả chúng theo thứ tự thời gian để
  hiển thị. Nếu còn lịch sử cũ, UI hiện nút **Load earlier messages**.
- Nút đó gửi `before_message_id=<id cũ nhất đang có>` để lấy trang cũ hơn. UI
  prepend các message này và giữ nguyên vị trí scroll của người dùng.
- Trong khi run đang hoạt động, browser chỉ gọi
  `after_message_id=<id mới nhất đang có>`. Response chỉ chứa message phát sinh
  sau cursor (thường là câu trả lời assistant), không tải lại lịch sử đang xem.
- Tin nhắn user được append lạc quan ngay sau khi backend trả `202`, vì backend
  đã persist message đó trước khi trả response.

Database có composite index `(conversation_id, id)` cho các query cursor này.
Đây là index đúng với `WHERE conversation_id = ... AND id <|> cursor ORDER BY
id`, nên không phải scan/skip nhiều row như offset pagination. Không dùng cache
global cho chat vì state thay đổi nhanh và được phân quyền theo user/project;
delta polling là chính xác hơn và tránh trả dữ liệu cũ.

Trước thay đổi này, state endpoint có giới hạn 80 row nhưng sắp xếp tăng dần
trước khi `LIMIT`, nên conversation dài có thể trả 80 message cũ nhất. Chiến
lược cursor mới vừa giảm payload polling vừa bảo đảm luôn thấy câu trả lời mới.

## Không nằm trong phạm vi hiện tại

- Không live refresh GA4/GSC/DataForSEO/LibreCrawl từ chat.
- Không chạy audit, crawl hoặc sửa dữ liệu project từ chat.
- Không có streaming token; UI dùng polling và typing indicator.
- Không có danh sách/đổi tên/archive nhiều conversation trên UI.
- MCP server chưa nằm trên execution path. Tool registry được thiết kế
  transport-neutral để sau này có thể được bọc qua MCP, nhưng hiện chat đọc
  database nội bộ trực tiếp để nhanh và an toàn hơn.

## Source code chính

- `pipeline/app/routes/main.py`: route tạo/state/run của chat.
- `pipeline/services/audit_worker.py`: claim và chạy Copilot job nền.
- `pipeline/services/copilot_agent.py`: bounded reasoning/tool-calling loop.
- `pipeline/services/copilot_history.py`: cursor pagination cho lịch sử chat.
- `pipeline/services/tool_registry.py`: contract, validation và context của tool.
- `pipeline/services/copilot_tools.py`: truy vấn read-only cho dữ liệu SEO.
- `pipeline/services/copilot_provider.py`: OpenRouter adapter.

## Delivery và kiểm tra

- Core agent + Health Score: commit `6548634`.
- UX conversation surface: commit `db8a34d`.
- Cursor history + delta polling: delivered with this feature-note update.
- Base chat migration: `j7e8f9a0b1c2_add_health_scores_and_copilot.py`.
- Cursor index migration: `k8f9a0b1c2d3_add_copilot_message_cursor_index.py`.
- Regression suite sau thay đổi cursor: `python -m pytest tests -q` → 53 passed.
- PostgreSQL migration đã chạy đến revision `k8f9a0b1c2d3`; index cursor được
  xác nhận trên database đang chạy.
