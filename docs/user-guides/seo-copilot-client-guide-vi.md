# Hướng dẫn sử dụng SEO Copilot

> Dành cho client và team vận hành. Tài liệu này giải thích bằng ngôn ngữ dễ hiểu cách dùng các màn hình chính, dữ liệu đến từ đâu, và AI Copilot có thể hoặc chưa thể làm gì.

**Phiên bản:** 1.0
**Cập nhật:** 20 tháng 08 năm 2026
**Phạm vi:** Dashboard Week 3 - Audit, Trends, Keywords, Health Score và AI SEO Copilot.

## Mục lục

1. SEO Copilot giúp gì cho bạn?
2. Chuẩn bị trước khi dùng
3. Bản đồ nhanh của một Project
4. Chạy phân tích (Run Analysis)
5. Đọc trang Overview và Health Score
6. Đọc xu hướng 30/60/90 ngày
7. Theo dõi từ khóa
8. Audit History và Snapshot
9. Dùng AI SEO Copilot
10. Dữ liệu nào AI đang dùng?
11. Các tình huống thường gặp
12. Lịch làm việc gợi ý
13. Từ điển thuật ngữ ngắn

## 1. SEO Copilot giúp gì cho bạn?

SEO Copilot là nơi tập trung dữ liệu SEO của một website vào một Project. Bạn có thể dùng nó để:

- chạy một lần kiểm tra website và lưu kết quả;
- xem lỗi kỹ thuật, thay đổi traffic, vị trí từ khóa và backlink;
- so sánh dữ liệu trong 30, 60 hoặc 90 ngày;
- xem điểm sức khỏe SEO tổng quát của Project; và
- hỏi AI Copilot về các dữ liệu đã lưu mà không phải tự đọc từng bảng.

Nói đơn giản: **audit thu thập dữ liệu**, **dashboard hiển thị dữ liệu**, còn **AI Copilot giúp bạn đọc và tóm tắt dữ liệu đó**.

> **Lưu ý quan trọng:** AI Copilot hiện chỉ đọc dữ liệu đã lưu trong Project. Khi bạn nhắn tin, nó không tự chạy crawl, không tự gọi Google Analytics/Search Console mới, và không sửa website.

## 2. Chuẩn bị trước khi dùng

Bạn không cần biết kỹ thuật để xem dashboard hoặc chat với AI. Tuy nhiên, để số liệu đầy đủ, Admin cần chuẩn bị Project trước.

| Cần có | Vì sao cần | Nếu chưa có |
| --- | --- | --- |
| Website/domain đúng | Để crawler biết website nào cần kiểm tra | Audit có thể không chạy đúng website |
| Quyền Google Analytics 4 (GA4) | Để có Sessions/Users | Thẻ GA4 và phần traffic có thể trống |
| Quyền Google Search Console (GSC) | Để có Clicks, Impressions, CTR và vị trí tìm kiếm | Thẻ GSC và phần organic search có thể trống |
| Danh sách từ khóa cần theo dõi | Để biết thứ hạng và biến động keyword | Tab Keywords chưa có dữ liệu hữu ích |
| Ít nhất một Full audit hoàn tất | Để có crawl issues, backlink và Snapshot đầu tiên | Một số màn hình sẽ báo chưa có dữ liệu |

### Ai nên làm gì?

- **Client/team marketing:** xem dashboard, chạy audit theo quy trình đã thống nhất, đọc kết quả, hỏi AI và theo dõi việc cần làm.
- **Admin/team kỹ thuật:** tạo Project, kết nối tài khoản Google, thêm keyword/competitor, cấu hình AI và xử lý lỗi kết nối nếu có.

Nếu không chắc GA4 hoặc GSC đã được kết nối chưa, mở Project và xem phần **Project Details** trên tab Overview. Nếu cần thay đổi, dùng nút **Settings** hoặc nhờ Admin.

## 3. Bản đồ nhanh của một Project

Sau khi mở một Project, bạn sẽ thấy bốn tab chính.

| Tab | Dùng khi nào? | Bạn sẽ thấy gì? |
| --- | --- | --- |
| **Overview** | Muốn biết tình hình nhanh và hỏi AI | Health Score, lỗi kỹ thuật quan trọng, chi tiết Project, đối thủ và AI Copilot |
| **Trends** | Muốn biết chỉ số đi lên hay đi xuống theo thời gian | GA4 Sessions, GSC Clicks/CTR, crawl issues, backlinks và biểu đồ chi tiết |
| **Keywords** | Muốn biết từ khóa nào tăng/giảm | Vị trí hiện tại, vị trí trước đó, mức thay đổi, filter Winners/Losers/Page 1/Page 2 và export CSV |
| **Audit History** | Muốn xem lại các lần chạy trước | Các Snapshot đã lưu, trạng thái và dữ liệu tóm tắt của từng lần audit |

Hệ thống không tải toàn bộ dữ liệu nặng ngay lúc mở Project. Ví dụ, tab Trends, Keywords và Audit History chỉ tải khi bạn mở tab đó. Vì vậy trang Project sẽ vào nhanh hơn, kể cả khi đã có nhiều Snapshot.

## 4. Chạy phân tích (Run Analysis)

### Khi nào nên chạy?

- Khi mới tạo Project hoặc vừa kết nối dữ liệu lần đầu.
- Sau khi website có thay đổi lớn: thay template, chuyển URL, đổi robots.txt, triển khai nội dung lớn, đổi redirect...
- Theo lịch định kỳ, thường là một lần/tháng cho Full audit.
- Khi chỉ cần kiểm tra lại vị trí các keyword đang theo dõi, dùng **Ranking check only** để nhẹ hơn.

### Các bước chạy

1. Mở Project cần kiểm tra.
2. Bấm **Run Analysis** ở góc phải.
3. Chọn một trong hai loại chạy.
4. Chọn phạm vi crawl nếu chạy Full audit.
5. Xác nhận và theo dõi khung **Live Analysis Progress** xuất hiện phía trên.
6. Khi trạng thái hoàn tất, mở Overview, Trends, Keywords hoặc Audit History để xem dữ liệu mới.

### Chọn loại chạy nào?

| Lựa chọn | Hệ thống làm gì? | Phù hợp khi |
| --- | --- | --- |
| **Full audit** | Crawl website, lấy GA4, GSC, ranking keyword, backlink Project và insight đối thủ | Kiểm tra định kỳ hoặc cần bức tranh SEO đầy đủ |
| **Ranking check only** | Chỉ kiểm tra vị trí keyword, URL xếp hạng, search volume và vị trí đối thủ | Muốn theo dõi keyword nhanh mà không cần crawl/traffic/backlink mới |

### Chọn phạm vi crawl

| Crawl mode | Ý nghĩa dễ hiểu | Lúc nên dùng |
| --- | --- | --- |
| **Full website** | Quét toàn bộ website có thể tìm được trong phạm vi cho phép | Audit định kỳ hoặc lần đầu |
| **Selected URLs** | Chỉ quét các URL bạn nhập, mỗi dòng một URL | Kiểm tra landing page/nhóm trang cụ thể |
| **Folder / path** | Chỉ quét một phần website, ví dụ `/blog/` | Website lớn, hoặc cần kiểm tra một chuyên mục |
| **Reuse previous crawl** | Không crawl lại; dùng dữ liệu crawl lần trước, các nguồn khác vẫn có thể được refresh theo loại chạy | Muốn tiết kiệm thời gian khi phần kỹ thuật chưa thay đổi |

> **Mẹo:** Nếu chưa chắc nên chọn gì, bắt đầu với **Full audit + Full website**. Với website lớn, hỏi người phụ trách kỹ thuật trước khi dùng Full website để thống nhất phạm vi và chi phí.

### Hiểu trạng thái audit

| Trạng thái | Nghĩa là gì? | Bạn nên làm gì? |
| --- | --- | --- |
| **Pending/Running** | Audit đang chờ hoặc đang chạy | Chờ tiến trình hoàn tất; không cần gửi lại nhiều lần |
| **Complete** | Các bước đã chạy xong | Xem kết quả mới và tạo action plan |
| **Partial** | Một phần dữ liệu đã có nhưng một nguồn/bước chưa hoàn tất | Vẫn xem được phần có dữ liệu; kiểm tra ghi chú/lỗi trước khi kết luận |
| **Failed** | Audit không hoàn tất | Báo Admin kèm thời gian chạy và ảnh chụp lỗi nếu có |

## 5. Đọc trang Overview và Health Score

Overview là màn hình trả lời nhanh câu hỏi: **Website này đang khỏe hay đang cần chú ý điều gì trước?**

### Health Score là gì?

Health Score là điểm tổng hợp từ 0 đến 100, dùng để ưu tiên công việc. Nó gồm bốn nhóm dữ liệu:

| Nhóm | Trọng số thông thường | Ý nghĩa thực tế |
| --- | ---: | --- |
| **Technical** | 35% | Lỗi kỹ thuật khi crawl, ví dụ lỗi trang, redirect, metadata hoặc cấu trúc |
| **Organic** | 30% | Xu hướng GA4 Sessions, GSC Clicks và CTR |
| **Keywords** | 20% | Độ phủ keyword, tỷ lệ Top 10 và vị trí trung bình |
| **Backlinks** | 15% | Sự thay đổi referring domains/backlinks giữa các audit |

Điểm không tự coi dữ liệu chưa có là 0. Thay vào đó, hệ thống hiển thị **confidence** (mức độ đủ dữ liệu). Vì vậy, Project mới có thể có điểm dựa trên ít nhóm dữ liệu hơn; đừng kết luận vội chỉ từ một con số.

### Cách dùng Health Score đúng cách

1. Xem nhãn màu và điểm để biết mức ưu tiên.
2. Đọc phần phân rã theo Technical, Organic, Keywords và Backlinks.
3. Chọn nhóm thấp nhất để điều tra tiếp ở Trends, Keywords hoặc phần Website Issues.
4. Hỏi AI: “Dựa trên Health Score mới nhất, tôi nên xử lý ba việc nào trước?”
5. Sau khi sửa website, chạy Full audit mới để có Snapshot và điểm mới.

> **Không nên:** coi Health Score là báo cáo cuối cùng hoặc so sánh cứng nhắc giữa hai Project có mức confidence rất khác nhau.

### Website Issues

Phần Website Issues lấy từ crawl mới nhất. Đây là nơi phù hợp để tìm việc kỹ thuật cụ thể. Hãy ưu tiên các issue có số lượng lớn, ảnh hưởng tới URL quan trọng, hoặc xuất hiện sau một đợt thay đổi website.

## 6. Đọc xu hướng 30/60/90 ngày

Mở tab **Trends**, chọn **30 days**, **60 days** hoặc **90 days**, sau đó bấm vào một thẻ chỉ số để xem biểu đồ lớn hơn và bảng điểm dữ liệu.

### Năm chỉ số chính

| Chỉ số | Nó nói gì với bạn? | Dữ liệu được ghi khi nào? |
| --- | --- | --- |
| **GA4 Sessions** | Lượt truy cập/phiên của website | Theo ngày |
| **GSC Clicks** | Số lượt người bấm website từ Google Search | Theo ngày |
| **GSC CTR** | Tỷ lệ người thấy kết quả rồi bấm vào | Theo ngày, tính theo trọng số để chính xác hơn |
| **Crawl Issues** | Tổng số lỗi/tín hiệu kỹ thuật từ một lần crawl | Mỗi lần audit hoàn tất |
| **Backlinks** | Hồ sơ backlink/referring domains | Mỗi lần audit hoàn tất |

### Hệ thống so sánh như thế nào?

- **30 ngày:** so với 30 ngày ngay trước đó; giao diện gọi là MoM.
- **60/90 ngày:** so với một khoảng thời gian ngay trước đó có độ dài bằng nhau; giao diện gọi là Period change.
- **YoY:** so với đúng khoảng thời gian cùng kỳ năm trước, chỉ hiện khi hệ thống đã có đủ dữ liệu cũ.

Ví dụ: thẻ 30 ngày có thể cho biết Sessions tăng/giảm so với 30 ngày trước. Đây là so sánh công bằng hơn là chỉ lấy ngày đầu và ngày cuối của biểu đồ.

### Vì sao 30/60/90 đôi khi giống nhau?

Điều này thường không phải lỗi. Crawl issues và backlinks chỉ có một điểm dữ liệu khi có một audit hoàn tất. Nếu bạn mới có các Snapshot trong 30 ngày gần đây, cả 30/60/90 đều chỉ nhìn thấy cùng các lần audit đó.

GA4/GSC thì khác: chúng là dữ liệu theo ngày. Khi daily history đã tích lũy đủ, 30/60/90 phải có số ngày và kết quả khác nhau. Nếu chúng trống, đọc phần xử lý sự cố bên dưới.

### Một điều quan trọng về tốc độ và chi phí

Mở Trends **không** gọi Google, DataForSEO hay chạy crawl mới. Dashboard chỉ đọc dữ liệu đã lưu; biểu đồ chỉ tải khi bạn thật sự mở tab Trends. Điều này giúp Project tải nhanh và tránh phát sinh chi phí ngoài ý muốn.

## 7. Theo dõi từ khóa

Tab **Keywords** trả lời câu hỏi: “Từ khóa nào đang lên, từ khóa nào đang tụt và tôi nên xem từ khóa nào trước?”

### Cách dùng

1. Mở tab **Keywords**.
2. Dùng search để tìm một keyword cụ thể.
3. Dùng filter để xem:
   - **Winners:** thứ hạng cải thiện;
   - **Losers:** thứ hạng giảm;
   - **Page 1:** đang ở trang kết quả đầu tiên;
   - **Page 2:** gần trang 1, thường là cơ hội tối ưu tốt.
4. Chọn device nếu Project có dữ liệu theo thiết bị.
5. Xem Latest position, Previous position, Movement và biểu đồ mini.
6. Export CSV khi cần chia sẻ hoặc làm báo cáo ngoài hệ thống.

### Lưu ý

- Keyword được lưu ngay khi bạn thêm vào danh sách theo dõi.
- Chi tiết xếp hạng chỉ xuất hiện sau ít nhất một **Ranking check only** hoặc **Full audit** thành công.
- Một keyword mới không có lịch sử sẽ chưa thể hiện movement đáng tin cậy ngay.

## 8. Audit History và Snapshot

Mỗi lần audit tạo một **Snapshot** - có thể hiểu là “ảnh chụp tình trạng SEO tại thời điểm chạy”. Snapshot giúp bạn quay lại xem dữ liệu và báo cáo của một lần kiểm tra cũ.

### Snapshot đang phục vụ những gì?

| Dùng Snapshot cho | Vì sao cần giữ? |
| --- | --- |
| Báo cáo audit tại thời điểm đó | Có thể đối chiếu lại điều AI/report đã dựa vào |
| Crawl issues | Cho biết lỗi kỹ thuật ghi nhận lúc audit |
| Backlink history | Ghi lại hồ sơ backlink/referring domains tại từng audit |
| Keyword history | Cung cấp một phần lịch sử thay đổi ranking |
| Trends kỹ thuật/backlink | So sánh các lần audit theo thời gian |

GA4/GSC daily trend được lưu riêng theo ngày để tránh cộng trùng traffic/search data từ nhiều Snapshot chồng thời gian. Vì vậy Snapshot không trở nên vô dụng khi có AI; nó vẫn là mốc lịch sử quan trọng cho audit, crawl và backlinks.

> **Cẩn thận khi xóa Snapshot:** thao tác này xóa record audit và các dữ liệu gắn với nó. Chỉ xóa bản chạy thử hoặc bản không còn cần thiết, sau khi chắc chắn không cần dùng nó cho so sánh/báo cáo.

## 9. Dùng AI SEO Copilot

AI Copilot nằm ở tab **Overview**. Nó phù hợp khi bạn muốn nhận một câu trả lời có ngữ cảnh thay vì tự ghép nhiều bảng số liệu.

### Cách hỏi

1. Mở tab **Overview** của đúng Project.
2. Gõ câu hỏi vào ô chat hoặc bấm một gợi ý có sẵn.
3. Bấm gửi hoặc nhấn Enter.
4. Chờ trạng thái đang xử lý. Trong lúc AI trả lời, hãy đợi thay vì gửi nhiều câu cùng một chat.
5. Đọc câu trả lời và các source chip, ví dụ Daily metrics hoặc Snapshot #... để biết AI đã dựa vào loại dữ liệu nào.

### Câu hỏi nên dùng

- “Dựa trên Health Score mới nhất, ba việc tôi nên làm trước là gì?”
- “Tóm tắt traffic và hiệu quả Google Search trong 30 ngày gần nhất.”
- “Keyword nào tụt mạnh và nên kiểm tra trước?”
- “Các crawl issue quan trọng nhất từ audit mới nhất là gì?”
- “Backlink/referring domains thay đổi như thế nào qua các audit gần đây?”
- “So sánh tình hình organic hiện tại với giai đoạn trước và đề xuất action plan.”

### Cách AI trả lời - giải thích ngắn gọn

AI không được gửi toàn bộ database cùng lúc. Khi bạn hỏi, nó chọn các “ngăn dữ liệu” cần thiết, ví dụ traffic, keyword hoặc crawl issues; hệ thống chỉ đưa dữ liệu của Project hiện tại cho nó; sau đó AI tổng hợp thành câu trả lời.

Điều này giúp câu trả lời có căn cứ hơn, giới hạn dữ liệu cần đọc và giữ chat nhanh hơn khi Project đã có nhiều lịch sử.

### AI hiện chưa làm gì?

| AI làm được | AI chưa làm trong phiên bản hiện tại |
| --- | --- |
| Phân tích dữ liệu đã lưu và trả lời theo ngữ cảnh Project | Tự chạy Full audit/crawl từ chat |
| Chọn đúng loại dữ liệu đã lưu để đọc | Tự gọi GA4, GSC hoặc DataForSEO để lấy số live mới |
| Tóm tắt keyword, technical issues, traffic, backlink, competitor data và Health Score | Tự sửa website, thêm keyword hoặc thay đổi cài đặt |
| Lưu lịch sử chat để mở lại trang vẫn thấy | Tự hành động bên ngoài mà không có sự xác nhận của bạn |

> **Về MCP server:** đây là phần kỹ thuật để có thể kết nối AI với các công cụ live trong tương lai. Hiện client không cần dùng hay cài gì thêm; chat chưa sử dụng nó.

## 10. Dữ liệu nào AI đang dùng?

Khi có dữ liệu, AI có thể đọc các nguồn sau của chính Project đang mở:

| Loại câu hỏi | Dữ liệu AI có thể đọc | Mốc dữ liệu |
| --- | --- | --- |
| Traffic/organic performance | GA4 Sessions và GSC Clicks/Impressions/CTR/Position | Daily metrics đã lưu |
| Keyword | Thứ hạng keyword theo dõi và movement | Kết quả ranking đã lưu |
| Technical SEO | Nhóm crawl issues từ crawl hoàn tất mới nhất | Snapshot crawl mới nhất |
| Backlink | Backlinks/referring domains | Lịch sử Snapshot audit |
| Competitor | Insight đối thủ thuộc Project | Insight đã lưu |
| Health | Điểm, các thành phần và confidence | Health Score đã lưu |

Nếu bạn vừa thay đổi website hoặc số liệu Google vừa thay đổi trong hôm nay nhưng chưa chạy/sync audit thích hợp, AI chưa thể biết thay đổi đó. Trong trường hợp này, hãy chạy loại audit phù hợp hoặc nhờ Admin kiểm tra kết nối dữ liệu.

## 11. Các tình huống thường gặp

### “AI nói chưa có dữ liệu”

Có thể Project chưa có Full audit hoàn tất, chưa có keyword ranking, hoặc nguồn GA4/GSC chưa kết nối. Hãy kiểm tra Audit History và Project Details trước.

### “Tôi không gửi được câu thứ hai ngay”

Mỗi conversation chỉ xử lý một câu hỏi tại một thời điểm để tránh AI lẫn ngữ cảnh và không tạo hai job trùng nhau. Chờ câu trả lời hiện tại xong rồi gửi tiếp.

### “GA4/GSC ở Trends trống”

Nguyên nhân phổ biến là tài khoản Google chưa có quyền, Project chưa cấu hình đúng GA4/GSC, hoặc Project được audit trước khi daily trend được lưu. Một Full audit thành công trong cấu hình đúng sẽ tiếp tục tích lũy history. Admin có thể thực hiện backfill riêng khi cần lịch sử cũ.

### “30/60/90 ngày hiện giống nhau”

Với crawl/backlink, đây có thể là đúng vì chỉ có vài lần audit gần đây. Với GA4/GSC, hãy kiểm tra xem Daily metrics đã có đủ lịch sử hay chưa.

### “Health Score thấp nhưng tôi chưa có đủ dữ liệu”

Đọc cả **confidence** và breakdown. Hệ thống không xem dữ liệu thiếu là 0, nhưng điểm có thể mới phản ánh một phần bức tranh. Chạy thêm audit và hoàn thiện kết nối dữ liệu trước khi dùng điểm cho quyết định lớn.

### “Audit là Partial”

Bạn vẫn có thể dùng phần dữ liệu đã hoàn tất, nhưng hãy coi kết quả là chưa đủ. Xem issue/log hoặc nhờ Admin xác định nguồn nào chưa chạy xong trước khi so sánh với Snapshot khác.

## 12. Lịch làm việc gợi ý

### Mỗi tuần

1. Mở **Keywords** và xem Losers/Page 2.
2. Mở **Trends 30 days** để xem Sessions, Clicks và CTR.
3. Hỏi AI: “Điều gì thay đổi đáng chú ý trong tuần/30 ngày qua?”
4. Ghi lại 1-3 việc ưu tiên, có người chịu trách nhiệm và hạn hoàn thành.

### Mỗi tháng

1. Chạy **Full audit** theo phạm vi đã thống nhất.
2. Đọc Health Score và Website Issues.
3. So sánh Trends 30/60/90 ngày.
4. Xem backlink và keyword movement.
5. Hỏi AI tạo một action plan ngắn, sau đó kiểm tra lại bằng các số liệu hiển thị trên dashboard.
6. Giữ Snapshot audit quan trọng để có lịch sử báo cáo.

## 13. Từ điển thuật ngữ ngắn

| Thuật ngữ | Nghĩa dễ hiểu |
| --- | --- |
| **Audit** | Một lần hệ thống kiểm tra SEO và thu thập dữ liệu |
| **Snapshot** | Ảnh chụp dữ liệu của một lần audit tại thời điểm cụ thể |
| **Crawl** | Bot đi qua website để đọc URL, lỗi và tín hiệu kỹ thuật |
| **GA4 Sessions** | Số phiên truy cập website trong Google Analytics 4 |
| **GSC Clicks** | Số lượt người bấm website từ kết quả Google Search |
| **CTR** | Tỷ lệ click trên số lần website xuất hiện trong Google Search |
| **Keyword movement** | Mức thay đổi vị trí xếp hạng của từ khóa |
| **Backlink** | Link từ website khác trỏ về website của bạn |
| **Referring domain** | Tên miền khác có ít nhất một backlink trỏ về website của bạn |
| **Health Score** | Điểm tổng hợp để ưu tiên việc SEO cần làm |
| **Confidence** | Mức độ đầy đủ của dữ liệu dùng để tính điểm |

## Ghi nhớ nhanh

1. Muốn dữ liệu mới hơn: chạy audit phù hợp, không chờ chat tự refresh.
2. Muốn hiểu thay đổi theo thời gian: vào Trends, chọn 30/60/90 ngày.
3. Muốn theo dõi vị trí: vào Keywords, ưu tiên Losers và Page 2.
4. Muốn hỏi “vì sao” hoặc “nên làm gì trước”: dùng AI Copilot, rồi đối chiếu source chip và dashboard.
5. Muốn nhìn lại lịch sử: vào Audit History và giữ các Snapshot quan trọng.
