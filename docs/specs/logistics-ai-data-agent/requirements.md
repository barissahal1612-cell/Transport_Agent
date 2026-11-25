# Requirements Document

## Introduction

Bu doküman, Logistics AI Assistant için Faz 2 kapsamını tanımlar: Excel kaynaklı lojistik verisinin yapılandırılmış veri kaynağı olarak sunulması, `role_user` tablosuna dayalı kimlik doğrulama, dinamik izin yönetimi (Admin Panel), Strands `@tool` fonksiyonları, ajan sistem istemi ve rol bazlı dashboard.

Mevcut `Logistic_AI` projesi (Strands Agents + Amazon Bedrock AgentCore Runtime, runtime adı `agent`, `agentcore deploy`) korunur. Faz 1'deki modüler yapı (Shared_Auth_Package, Agent_Backend, Streamlit_Client) genişletilir; gereksiz yeniden yazım yapılmaz.

Kaynak dosya: `Logistic_AI/Data/Agent_AWS_2026-11-24.xlsx`. Sheet ve kolon adları değiştirilmez.

### Kapsam Notları

- "Knowledge Base" terimi bu dokümanda **yapılandırılmış, kesin eşleşmeli veri deposu** anlamındadır (Data_Store). Anahtar sorgularında vektör/anlamsal arama kullanılmaz.
- AWS dağıtımı (`agentcore deploy`, DynamoDB tablo oluşturma, veri yükleme) kullanıcı onayı olmadan yapılmaz.
- Excel'deki `permissions` sheet'i kullanıcı isteğinde belirtilmemiştir; yalnızca başlangıç izinlerinin tohumu (seed) olarak kullanılır ve Data_Store'a alınmaz.

## Glossary

- **Excel_Source**: `Agent_AWS_2026-11-24.xlsx` dosyası.
- **Data_Store**: Operasyonel tabloların kesin eşleşmeli sorgulanabildiği veri deposu.
- **Operational_Table**: `question1`, `question2`, `question3`, `question4`, `question5`, `critical`, `summary_df`.
- **Auth_Table**: `role_user` ve `permissions` sheet'leri. Data_Store'a ve LLM bağlamına asla alınmaz.
- **Ingestion_Tool**: Excel_Source'u okuyup Data_Store'a, User_Store'a ve Permission_Store'a yükleyen yinelenebilir betik.
- **User_Store**: Kullanıcı kayıtlarını (USERID, USERNAME, ROLE, şifre özeti, aktiflik) tutan kalıcı DynamoDB tablosu.
- **Permission_Store**: Rol ve kullanıcı bazlı izinleri tutan kalıcı DynamoDB tablosu.
- **Role**: `SUPPLIER`, `MATERIAL_RESPONSIBLE`, `TRANSPORT_OFFICE`, `ADMIN`.
- **Resource**: İzin kontrolüne tabi tablo (`TABLE`) veya fonksiyon (`FUNCTION`).
- **Permission_Service**: Her Tool çağrısından önce backend'de izin kararını veren modül.
- **Auth_Service**: Kullanıcı adı ve şifreyi doğrulayan ve Session_Token üreten modül.
- **Admin_Service**: Admin_Panel'in çağırdığı, izin ve kullanıcı durumunu değiştiren backend modülü.
- **Session_Token**: Başarılı girişten sonra üretilen, kısa ömürlü, imzalı oturum belirteci.
- **Agent_Backend**: AgentCore Runtime üzerindeki Strands ajanı.
- **Streamlit_Client**: Giriş ekranı, sohbet, dashboard ve Admin Panel'i sunan istemci.
- **Dashboard**: `summary_df` verisinden üretilen KPI ve grafik ekranı.
- **Admin_Panel**: ADMIN rolüne özel izin ve kullanıcı yönetimi ekranı.
- **Key_ID**: Fonksiyonun zorunlu arama anahtarı (`shipment_id`, `materialno`, `mip`).

## Requirements

### Requirement 1: Veri Kaynağı ve Veri Deposu

**User Story:** Bir geliştirici olarak, Excel verisinin yapılandırılmış ve kesin eşleşmeli bir veri deposuna güvenli aktarılmasını istiyorum; böylece ajan doğru ve tutarlı yanıt versin.

#### Acceptance Criteria

1. THE Ingestion_Tool SHALL Excel_Source içindeki sheet adlarını ve kolon adlarını değiştirmeden Operational_Table'lara aktarmak.
2. THE Ingestion_Tool SHALL `role_user` ve `permissions` sheet'lerini Data_Store'a yazmamak.
3. THE Ingestion_Tool SHALL `shipment_id`, `materialno`, `supplier_code` ve `mip` değerlerini string olarak saklamak; baştaki sıfırları ve sondaki harfleri (ör. `07358034660E`) korumak.
4. THE Ingestion_Tool SHALL sayısal görünen anahtar alanları string'e çevirirken ondalık ek (`.0`) eklememek.
5. WHEN `question1`, `question2`, `question4` veya `question5` JSON kolonları işlenirken THE Ingestion_Tool SHALL JSON'u güvenli parse etmek.
6. IF bir JSON kaydı geçersizse THEN THE Ingestion_Tool SHALL kaydı atlayıp hata raporuna (sheet, satır, hata türü) yazmak ve işlemi sürdürmek.
7. THE Ingestion_Tool SHALL işlem sonunda sheet bazında okunan, yüklenen ve atlanan kayıt sayısını raporlamak.
8. THE Data_Store SHALL Key_ID sorgularında yalnızca kesin eşleşme (normalize edilmiş string eşitliği) kullanmak; anlamsal benzerlik kullanmamak.
9. THE Data_Store SHALL Key_ID normalizasyonunda yalnızca baştaki ve sondaki boşlukları silmek ve büyük/küçük harf farkını yok saymak; sıfırları değiştirmemek.
10. THE Ingestion_Tool SHALL aynı dosya yeniden yüklendiğinde yinelenen kayıt oluşturmamak (idempotent yükleme).
11. THE Ingestion_Tool SHALL şifre veya kullanıcı verisini günlüğe yazmamak.

### Requirement 2: Kimlik Doğrulama

**User Story:** Bir kullanıcı olarak, kullanıcı adı ve şifremle giriş yapmak ve çıkış yapmak istiyorum.

#### Acceptance Criteria

1. THE Streamlit_Client SHALL kullanıcı adı alanı, maskeli şifre alanı ve giriş butonu içeren bir giriş ekranı göstermek.
2. THE Ingestion_Tool SHALL `role_user` kayıtlarını (ROLE, USERID, USERNAME, Password) User_Store'a aktarırken şifreyi yalnızca tuzlu ve yavaş bir özet algoritmasıyla (argon2id) saklamak.
3. THE sistem SHALL şifreyi açık metin olarak User_Store'da, uygulamada, günlükte, iz kaydında veya LLM bağlamında bulundurmamak.
4. THE Ingestion_Tool SHALL `USERID` değerini (ör. `129-01`, `ADMIN001`) string olarak saklamak.
5. THE Auth_Service SHALL kullanıcı adı eşleşmesini büyük/küçük harf duyarlı yapmak ve kullanıcı adı ile şifre hatalarında aynı genel hata mesajını döndürmek.
6. WHEN kimlik bilgileri geçerli ve kullanıcı aktifse THE Auth_Service SHALL USERID, USERNAME ve ROLE bilgilerini içeren imzalı bir Session_Token üretmek.
7. IF kullanıcı pasifse THEN THE Auth_Service SHALL girişi reddetmek ve şifrenin doğru olup olmadığını belli etmemek.
8. THE Session_Token SHALL en fazla 30 dakika geçerli olmak ve şifre içermemek.
9. WHEN ardışık 5 başarısız giriş denemesi olursa THE Auth_Service SHALL ilgili kullanıcıyı 15 dakika kilitlemek.
10. WHEN kullanıcı çıkış yaparsa THE Streamlit_Client SHALL oturum durumunu (token, USERID, USERNAME, ROLE, sohbet geçmişi) temizleyip giriş ekranına dönmek.
11. THE Auth_Service SHALL başarılı ve başarısız girişleri, çıkışları ve kilitlenmeleri şifre içermeyen denetim kaydı olarak yazmak.

### Requirement 3: Dinamik İzin Yönetimi

**User Story:** Bir yönetici olarak, rol ve kullanıcı bazlı izinleri kod değişikliği olmadan yönetmek istiyorum.

#### Acceptance Criteria

1. THE Permission_Store SHALL rol bazlı ve kullanıcı bazlı izin kayıtlarını (Resource türü, Resource adı, izinli/yasak) kalıcı saklamak.
2. WHEN Permission_Store ilk kez doldurulursa THE Ingestion_Tool SHALL `SUPPLIER`, `MATERIAL_RESPONSIBLE` ve `TRANSPORT_OFFICE` rollerine tüm Operational_Table ve fonksiyonlar için izin vermek.
3. THE Permission_Service SHALL Auth_Table'lara (`role_user`, `permissions`) hiçbir rol veya kullanıcı için erişim tanımlanmasına izin vermemek.
4. THE Permission_Service SHALL izin kararını şu öncelikle vermek: kullanıcı bazlı kayıt, rol bazlı kayıt, varsayılan ret.
5. IF kullanıcı veya rol için kayıt yoksa THEN THE Permission_Service SHALL erişimi reddetmek (deny-by-default).
6. THE Permission_Service SHALL izin kararını yalnızca Session_Token'dan doğrulanmış USERID'ye göre User_Store ve Permission_Store'dan okuyarak vermek; istemcinin veya LLM'in bildirdiği rol veya izne güvenmemek.
7. WHEN bir izin değişirse THE Permission_Service SHALL değişikliği en geç 60 saniye içinde uygulamak; kod değişikliği veya yeniden dağıtım gerektirmemek.
8. THE Permission_Service SHALL pasif kullanıcının tüm Tool çağrılarını reddetmek.
9. THE Permission_Service SHALL ret kararlarını (USERID, ROLE, Resource, zaman) denetim kaydına yazmak.

### Requirement 4: ADMIN Rolü ve Admin Panel

**User Story:** Bir ADMIN olarak, izinleri ve kullanıcı durumunu bir panelden yönetmek istiyorum.

#### Acceptance Criteria

1. THE Admin_Panel SHALL yalnızca ROLE değeri `ADMIN` olan, aktif ve doğrulanmış kullanıcılara gösterilmek.
2. THE Permission_Service SHALL `ADMIN` rolünü yalnızca User_Store'da ADMIN olarak kayıtlı kullanıcılara tanımak; hiçbir izin değişikliği bir kullanıcıya otomatik ADMIN yetkisi vermemek.
3. THE Admin_Panel SHALL kullanıcı bazlı izin eklemeyi, değiştirmeyi ve kaldırmayı desteklemek.
4. THE Admin_Panel SHALL rol bazlı izin eklemeyi, değiştirmeyi ve kaldırmayı desteklemek.
5. THE Admin_Panel SHALL bir rol veya kullanıcı için tablo erişimini vermeyi ve kaldırmayı desteklemek.
6. THE Admin_Panel SHALL bir rol veya kullanıcı için fonksiyon erişimini vermeyi ve kaldırmayı desteklemek.
7. THE Admin_Panel SHALL kullanıcıları aktif veya pasif yapmayı desteklemek.
8. THE Admin_Panel SHALL kullanıcı listesinde şifre veya şifre özeti göstermemek.
9. WHEN bir yönetim fonksiyonu çağrılırsa THE Admin_Service SHALL her çağrıda backend'de çağıranın ADMIN rolünü yeniden doğrulamak ve yetkisiz çağrıyı reddetmek.
10. THE Admin_Service SHALL ADMIN kullanıcısının kendi hesabını pasif yapmasını ve son aktif ADMIN'in pasif yapılmasını reddetmek.
11. THE Admin_Service SHALL her yönetim işlemini (kim, ne, hedef, eski/yeni değer, zaman) denetim kaydına yazmak.
12. THE Admin_Service SHALL kullanıcıya ADMIN rolü atamayı desteklememek; ADMIN rolü yalnızca Ingestion_Tool ile tanımlanmak.

### Requirement 5: Strands Agent Tool'ları

**User Story:** Bir kullanıcı olarak, lojistik sorularımı doğal dilde sormak ve doğru veriyle yanıt almak istiyorum.

#### Acceptance Criteria

1. THE Agent_Backend SHALL `Functions` sheet'indeki tanımlara göre şu fonksiyonları Strands `@tool` ile sunmak: `get_truck_location(shipment_id)`, `get_material_truck_allocation(materialno)`, `get_truck_route_info(shipment_id)`, `get_delayed_truck()`, `get_truck_tobearrived()`, `get_critical_part_status(mip)`.
2. THE `get_truck_location` SHALL `question1` tablosunu `shipment_id` kesin eşleşmesiyle sorgulamak.
3. THE `get_material_truck_allocation` SHALL `question2` tablosundan `materialno` kesin eşleşmesiyle tüm eşleşen kayıtları getirmek.
4. THE `get_truck_route_info` SHALL `question3` tablosundan `shipment_id` kesin eşleşmesiyle kayıtları `stop_sequence` sayısal artan sırasıyla getirmek.
5. THE `get_delayed_truck` SHALL `question4` tablosunun tamamını getirmek.
6. THE `get_truck_tobearrived` SHALL `question5` tablosunun tamamını getirmek.
7. THE `get_critical_part_status` SHALL `critical` tablosundan `mip` kesin eşleşmesiyle tüm eşleşen kayıtları getirmek.
8. IF zorunlu Key_ID boş veya eksikse THEN THE Tool SHALL veri sorgulamadan, eksik parametreyi bildiren ve kullanıcıdan bu bilgiyi isteyen yapılandırılmış bir yanıt döndürmek.
9. IF eşleşen kayıt yoksa THEN THE Tool SHALL "kayıt bulunamadı" sonucunu döndürmek ve ajan veri uydurmamak.
10. THE her Tool SHALL veri okumadan önce Permission_Service ile hem fonksiyon hem de tablo iznini kontrol etmek.
11. IF izin yoksa THEN THE Tool SHALL veri döndürmeden "Bu işlem için yetkiniz yok" yanıtı vermek.
12. THE her Tool SHALL kullanıcı kimliğini LLM'in verdiği parametrelerden değil, yalnızca doğrulanmış çağrı bağlamından almak.
13. THE Tool yanıtları SHALL Auth_Table verisi veya şifre içermemek.
14. IF bir kayıt bozuk veya eksikse THEN THE Tool SHALL istisna fırlatmak yerine kontrollü hata yanıtı döndürmek.

### Requirement 6: Agent Sistem İstemi

**User Story:** Bir kullanıcı olarak, Türkçe veya İngilizce soru sorup kısa, tablo biçiminde yanıt almak istiyorum.

#### Acceptance Criteria

1. THE Agent_Backend SHALL sistem istemini ayrı bir modülde (`prompts/system_prompt.py`) tutmak.
2. THE sistem istemi SHALL ajana doğal dildeki soruyu analiz edip doğru Tool'u seçmesini ve Türkçe ile İngilizce soruları desteklemesini söylemek.
3. THE sistem istemi SHALL yanıtların mümkün olduğunca kısa, profesyonel ve Markdown tablo biçiminde olmasını istemek.
4. THE sistem istemi SHALL ajana zorunlu Key_ID eksikse kullanıcıdan istemesini ve Tool sonucu dışında veri üretmemesini söylemek.
5. THE sistem istemi SHALL yetki kararını LLM'e bırakmamak; yetki kontrolü yalnızca Tool içinde backend'de yapılmak.
6. THE Agent_Backend SHALL model kimliğini `global.` önekli inference profile olarak yapılandırmak ve kimliği dağıtım sırasında `aws bedrock list-foundation-models` ile keşfetmek.

### Requirement 7: Dashboard

**User Story:** Bir transport ofisi veya malzeme sorumlusu olarak, girişten sonra sefer durumunu bir bakışta görmek istiyorum.

#### Acceptance Criteria

1. WHEN rolü `TRANSPORT_OFFICE` veya `MATERIAL_RESPONSIBLE` olan kullanıcı giriş yaparsa THE Streamlit_Client SHALL Dashboard'u otomatik göstermek.
2. THE Streamlit_Client SHALL `SUPPLIER` rolü için Dashboard'u göstermemek.
3. THE Dashboard SHALL KPI'ları `summary_df` tablosundan okumak: Tüm Seferler, Geciken Seferler, Tamamlanan Seferler, Devam Eden Seferler.
4. THE Dashboard SHALL Tamamlanan ve Devam Eden seferleri donut chart ile göstermek.
5. THE Dashboard SHALL Geciken Seferler'i ayrı KPI olarak ve gecikme oranı (Geciken / Tüm × 100, yüzde) ile göstermek.
6. THE Dashboard SHALL değerleri koda sabit yazmamak; her zaman Data_Store'dan okumak.
7. THE Dashboard SHALL gecikme oranını Geciken ve Tüm Seferler değerlerinden hesaplamak; `summary_df` içindeki `Gecikme Oranı` satırı hesaplanan değerden farklıysa uyarı kaydı yazmak.
8. IF Tüm Seferler sıfır ise THEN THE Dashboard SHALL oranı 0 göstermek ve sıfıra bölme hatası vermemek.
9. IF `summary_df` okunamaz veya bir KPI satırı eksikse THEN THE Dashboard SHALL genel hata mesajı göstermek ve uygulamayı çökertmemek.
10. THE Dashboard SHALL yalnızca `summary_df` tablosuna okuma izni olan kullanıcılara gösterilmek.
11. WHEN Excel_Source'ta formül bulunursa THE Ingestion_Tool SHALL hücrenin hesaplanmış değerini okumak; hesaplanmış değer yoksa kaydı hata raporuna yazmak.

### Requirement 8: Mimari ve Uyumluluk

**User Story:** Bir geliştirici olarak, mevcut mimariyi bozmadan modüler genişletme istiyorum.

#### Acceptance Criteria

1. THE sistem SHALL Authentication, Authorization, Data Access, Tools, Agent ve UI katmanlarını ayrı modüller olarak sunmak; modüller birbirlerinin alt çizgili iç öğelerini içe aktarmamak.
2. THE Agent_Backend SHALL mevcut Strands Agents ve AgentCore Runtime yapısıyla (`BedrockAgentCoreApp`, `@app.entrypoint`, lazy başlatma, runtime adı `agent`) uyumlu kalmak.
3. THE sistem SHALL `UNIFIED_TRACES_DESTINATION_ENABLED=true` ayarını korumak.
4. THE sistem SHALL Data_Store, User_Store ve Permission_Store erişimini arayüz (repository) arkasında soyutlamak; testler gerçek AWS olmadan çalışmak.
5. IF çalışma zamanı kimlik doğrulama yöntemi değişikliği (bkz. design.md Açık Karar 1) mevcut `agentcore.json` yetkilendirici ayarını etkiliyorsa THEN THE sistem SHALL değişikliği kullanıcı onayı alınmadan uygulamamak.
6. THE Agent_Backend SHALL DynamoDB ve Secrets Manager erişimini yalnızca `agentcore.json` içindeki `additionalPolicies` ile almak; IAM rolleri elle düzenlenmemek.
7. THE sistem SHALL AWS dağıtımını (deploy, tablo oluşturma, veri yükleme) kullanıcı onayı olmadan çalıştırmamak.
8. THE sistem SHALL bağımlılıkları ARM64 uyumlu seçmek ve test bağımlılıklarını `[dependency-groups].dev` içinde tutmak.

### Requirement 9: Güvenlik ve Gizli Bilgi Yönetimi

**User Story:** Bir güvenlik sorumlusu olarak, şifrelerin ve gizli anahtarların sızmamasını istiyorum.

#### Acceptance Criteria

1. THE Excel_Source SHALL sürüm kontrolüne eklenmemek (`Data/*.xlsx` `.gitignore` içindedir).
2. THE Session_Token imzalama anahtarı SHALL kaynak kodda veya sürüm kontrolünde bulunmamak; AWS Secrets Manager veya ortam değişkeninden okunmak.
3. THE günlük ve iz kayıtları SHALL şifre, şifre özeti, Session_Token ve imzalama anahtarı içermemek (mevcut `SanitizingFilter` kullanılır).
4. THE LLM bağlamı SHALL Auth_Table verisi, şifre veya Session_Token içermemek.
5. THE Tool ve Admin_Service girdileri SHALL doğrulanmak (uzunluk, karakter kümesi) ve DynamoDB sorguları parametreli API ile yapılmak.

### Requirement 10: Belgeleme

**User Story:** Bir geliştirici olarak, kurulumu ve işletimi belgelerden izlemek istiyorum.

#### Acceptance Criteria

1. THE README SHALL Türkçe olarak veri yükleme, kullanıcı ve izin tohumlama, yerel çalıştırma, Admin Panel kullanımı ve dağıtım öncesi onay adımlarını içermek.
2. THE spec dokümanları (requirements.md, design.md, tasks.md) SHALL Türkçe olmak.
