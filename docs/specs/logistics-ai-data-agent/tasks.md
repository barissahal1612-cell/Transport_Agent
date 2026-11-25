# Implementation Plan: logistics-ai-data-agent

## Overview

Bu plan, Faz 2 özelliklerini (Excel veri deposu, `role_user` tabanlı kimlik doğrulama, dinamik izin yönetimi, Admin Panel, Strands Tool'ları, sistem istemi, Dashboard) mevcut `Logistic_AI` projesinin üzerine, mevcut Strands + AgentCore yapısını koruyarak ekler. Dil Python 3.12+, testler pytest ve Hypothesis'tir.

Önemli kurallar:
- AWS kaynakları (DynamoDB tabloları, veri yükleme, `agentcore deploy`) kullanıcı onayı olmadan oluşturulmaz veya çalıştırılmaz. Kodlama görevleri yalnızca yerel bellek içi uyarlayıcılar ve `Stubber` ile test edilir.
- design.md "Açık Kararlar" 1 (AgentCore kimlik doğrulama seçeneği) kullanıcı tarafından netleştirilmeden `agentcore.json` yetkilendirici ayarı değiştirilmez.
- Yerel dev sunucusu daima 8081 numaralı bağlantı noktasıyla başlatılır (Faz 1 README'deki komut); 8080 asla kullanılmaz veya durdurulmaz.
- IAM rolleri elle düzenlenmez; DynamoDB ve Secrets Manager erişimi `additionalPolicies` ile tanımlanır.
- Excel dosyası ve şifreler sürüme eklenmez, günlüğe yazılmaz.

## Tasks

- [x] 1. Ortak altyapı ve proje yapısı
  - [x] 1.1 Bağımlılıkları ve paket iskeletini ekle
    - `app/agent/pyproject.toml` `[project].dependencies` içine `argon2-cffi` ekle (ARM64 wheel uyumluluğunu doğrula); `openpyxl` yalnızca `scripts/pyproject.toml` içinde olsun; `pytest` ve `hypothesis` yalnızca `[dependency-groups].dev` içinde kalsın
    - `app/agent/logistic_ai_data/` (boş `__init__.py`), `app/agent/tools/`, `scripts/ingest/` iskeletlerini oluştur; `streamlit_client/pyproject.toml` içine `plotly` ekle ve `logistic_ai_data` paketini yol bağımlılığı olarak bağla
    - _Requirements: 8.1, 8.8_

  - [x] 1.2 Anahtar normalizasyonu ve güvenli JSON yardımcılarını yaz
    - `logistic_ai_data/key_normalizer.py`: `normalize_key`, `to_key_string` (int/float/str → string, `.0` eklemeden)
    - `logistic_ai_data/json_safe.py`: `safe_json_loads` istisna fırlatmaz
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.9_

  - [ ]* 1.3 Normalizasyon ve güvenli parse için özellik testleri yaz
    - P1, P3: `Feature: logistics-ai-data-agent, Property 1/3`; dosya: `app/agent/tests/test_keys_json.py`
    - _Requirements: 1.3, 1.4, 1.5, 1.9_

- [x] 2. Veri erişim katmanı (Data_Store)
  - [x] 2.1 `DataRepository` arayüzünü ve `InMemoryDataRepository` uygulamasını yaz
    - `get_by_key(table, key)` ve `get_all(table)`; kesin eşleşme (normalize edilmiş); bilinmeyen tablo için hata
    - _Requirements: 1.8, 1.9, 8.4_

  - [x] 2.2 `DynamoDataRepository` uygulamasını yaz
    - `logistic-ai-kb` tablosu, PK/SK eşlemesi (design.md "Anahtar eşlemesi"); `Query` ile kesin PK; `question3` için SK sayısal sıra
    - Tablo adları ortam değişkeninden okunur; tablo oluşturma bu görevin kapsamı dışındadır
    - _Requirements: 1.8, 5.4, 8.4_

  - [ ]* 2.3 Kesin eşleşme ve sıralama için özellik testleri yaz
    - P2, P10; `Stubber` ile DynamoDB uyarlayıcı birim testleri; dosya: `app/agent/tests/test_data_repository.py`
    - _Requirements: 1.8, 5.4_

- [x] 3. Yükleme aracı (Ingestion_Tool)
  - [x] 3.1 Excel okuyucuyu yaz
    - `scripts/ingest/excel_reader.py`: `openpyxl` ile `data_only=True`; sheet/kolon adlarını korur; formül hücrelerinin hesaplanmış değerini okur, değer yoksa hata raporuna yazar; datetime → `YYYY-MM-DD HH:MM:SS`; anahtar kolonlar string
    - `role_user` ve `permissions` sheet'leri yalnızca kullanıcı/izin yükleyicisine verilir, Data_Store yükleyicisine verilmez
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.11_

  - [x] 3.2 Data_Store yükleyicisini ve raporlamayı yaz
    - `scripts/ingest/loader.py`: JSON kolonlarını `safe_json_loads` ile parse eder, bozuk kaydı atlayıp rapora yazar; `question2` JSON/kolon tutarlılığını doğrular; sheet bazında okunan/yüklenen/atlanan sayılarını raporlar
    - Yüklemeden önce ilgili sheet kayıtlarını `sheet-index` ile siler (idempotent); `--dry-run` varsayılandır, gerçek yazma `--apply` gerektirir
    - Rapor şifre veya kullanıcı verisi içermez
    - _Requirements: 1.5, 1.6, 1.7, 1.10, 1.11_

  - [x] 3.3 Kullanıcı ve izin tohumlayıcısını yaz
    - `scripts/ingest/seed.py`: `role_user` → argon2id özetli kullanıcı kayıtları (USERID string, `active=true`); `permissions` sheet'inden başlangıç izinleri (`ALLOWED` ∉ {0,1} veya bilinmeyen kaynak atlanır ve raporlanır)
    - Yeniden çalıştırma mevcut kullanıcı ve izin kayıtlarını ezmez (`attribute_not_exists`); düz metin şifre hiçbir yere yazılmaz veya günlüğe düşmez; `--apply` olmadan hiçbir yazma yapılmaz
    - _Requirements: 2.2, 2.3, 2.4, 3.2, 4.12, 1.11_

  - [ ]* 3.4 Yükleme ve tohumlama için testler yaz
    - P4, P14; gerçek Excel dosyası varsa sheet satır sayılarını ve bozuk JSON enjekte edilen satırın atlandığını doğrula; dosya: `app/agent/tests/test_ingest.py`
    - _Requirements: 1.5, 1.6, 1.10, 2.2, 3.2_

- [x] 4. Kimlik doğrulama (Authentication)
  - [x] 4.1 `PasswordHasher` ve `SessionTokenService` yaz
    - `logistic_ai_shared_auth/auth/passwords.py`: argon2id `hash`/`verify`
    - `auth/session_token.py`: HS256, `uid/usr/role/iat/exp`, 30 dk ömür; anahtar `SecretProvider` arayüzünden (Secrets Manager veya ortam değişkeni); `Clock` enjekte edilir
    - _Requirements: 2.2, 2.3, 2.6, 2.8, 9.2_

  - [x] 4.2 `UserRepository` arayüzü, bellek içi ve DynamoDB uygulamalarını yaz
    - `get_by_username`, `get_by_userid`, `set_active`, `record_failure`, `reset_failures`, `list_users`
    - _Requirements: 2.5, 2.7, 2.9, 4.7, 8.4_

  - [x] 4.3 `UserAuthService`'i yaz
    - Kullanıcı adı büyük/küçük harf duyarlı; kullanıcı yok, şifre hatalı, pasif hesap ve kilitli hesap aynı genel hata mesajını döner; kullanıcı yokken de sahte doğrulama yap (zamanlama farkını azalt); 5 ardışık hata → 15 dk kilit; her olay denetim kaydı (mevcut `JsonAuditLogger`)
    - _Requirements: 2.5, 2.6, 2.7, 2.9, 2.11_

  - [ ]* 4.4 Kimlik doğrulama için özellik testleri yaz
    - P4, P13; kilitleme, pasif hesap, genel hata mesajı eşitliği, günlükte şifre/özet/token olmaması; dosya: `app/agent/tests/test_auth.py`
    - _Requirements: 2.3, 2.5, 2.7, 2.9, 9.3_

- [x] 5. Yetkilendirme (Permission_Service ve Admin_Service)
  - [x] 5.1 `PermissionRepository` ve `PermissionService` yaz
    - Bellek içi ve DynamoDB uygulamaları (`logistic-ai-permissions`); karar sırası: kullanıcı yok/pasif → ret; `role_user`/`permissions` → ret; kullanıcı kaydı; rol kaydı; varsayılan ret; 30 sn TTL önbellek; ret denetim kaydı
    - `require_tool(userid, function, tables)`: hem `FUNCTION` hem `TABLE` izni zorunlu
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 5.10_

  - [x] 5.2 `AdminService` yaz
    - `set_user_active`, `set_permission`, `remove_permission`, `list_users`, `list_permissions`; her çağrıda aktif ADMIN doğrulaması; kendi hesabını ve son aktif ADMIN'i pasif yapma reddi; yalnızca bilinen kaynak adları; ADMIN rolü atama işlemi yok; her işlem denetim kaydı; işlem sonrası önbellek temizliği
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12_

  - [ ]* 5.3 Yetkilendirme ve yönetim için özellik testleri yaz
    - P5, P6, P7, P12; dosya: `app/agent/tests/test_authorization.py`
    - _Requirements: 3.3, 3.4, 3.5, 3.8, 4.2, 4.9, 4.10_

- [x] 6. Strands Tool'ları ve Agent
  - [x] 6.1 Tool koruma dekoratörünü ve altı `@tool` fonksiyonunu yaz
    - `tools/guard.py`: doğrulanmış `invocation_state["userid"]` kimliği; izin kontrolü; Key_ID boş/eksik → `missing_parameter`; kayıt yok → `not_found`; istisna → `error`
    - `tools/logistics_tools.py`: `get_truck_location`, `get_material_truck_allocation`, `get_truck_route_info` (stop_sequence sayısal artan), `get_delayed_truck`, `get_truck_tobearrived`, `get_critical_part_status`; çıktı Auth_Table verisi içermez
    - Strands `ToolContext` / `invocation_state` API'sini Strands MCP dokümanıyla doğrula
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 5.13, 5.14_

  - [x] 6.2 Sistem istemini ve model yükleyiciyi yaz
    - `prompts/system_prompt.py`: Türkçe/İngilizce, doğru Tool seçimi, kısa ve Markdown tablo biçimli yanıt, eksik Key_ID için kullanıcıdan isteme, veri uydurmama; yetki kararı LLM'e bırakılmaz
    - `model/load.py`: `global.` önekli inference profile; model kimliği sabit kodlanmaz, `aws bedrock list-foundation-models --by-provider Anthropic` ile keşfedilen değer ortam değişkeninden (`LOGISTIC_AI_MODEL_ID`) okunur
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 6.3 `agent_factory.py` ve `main.py` güncelle
    - Lazy `build_agent()`; `main.py`: `parse_payload` → Session_Token doğrula → kullanıcıyı User_Store'dan oku (pasifse reddet) → `invocation_state` ile ajanı çalıştır; Faz 1 placeholder akışı ve Cognito `TokenVerifier` yolu kullanımdan çıkarılır
    - Kimlik taşıma yöntemi design.md Açık Karar 1'e bağlıdır: `IdentityResolver` arayüzü ile uygula; `agentcore.json` değiştirilmez
    - `BedrockAgentCoreApp` içe aktarımı `bedrock_agentcore.runtime` altında kalır, `UNIFIED_TRACES_DESTINATION_ENABLED` korunur
    - _Requirements: 3.6, 5.12, 8.2, 8.3_

  - [ ]* 6.4 Tool ve Agent testlerini yaz
    - P8, P9, P10; izin yokken depo çağrısı olmaması, Key_ID eksikliği, bulunamadı, sıralama; Auth_Table verisinin LLM bağlamına girmemesi; dosya: `app/agent/tests/test_tools.py`
    - _Requirements: 5.8, 5.9, 5.10, 5.11, 5.13_

- [x] 7. Checkpoint - Backend testleri
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Streamlit_Client: Giriş, Dashboard ve Admin Panel
  - [x] 8.1 Giriş ekranını ve oturum yönetimini `role_user` akışına uyarla
    - Faz 1 `login_screen.py`/`manager.py` içinde `AuthService` bağımlılığı `UserAuthService` ile değiştirilir; oturuma yalnızca USERID, USERNAME, ROLE ve Session_Token yazılır; çıkışta tüm oturum ve sohbet geçmişi temizlenir
    - AgentCore çağrı taşıma katmanı Açık Karar 1'e bağlı `AgentCoreClient` uyarlayıcısı olarak değiştirilir
    - _Requirements: 2.1, 2.6, 2.8, 2.10_

  - [x] 8.2 Dashboard'u yaz
    - `ui/dashboard.py`, `dashboard/kpi.py`: `load_kpis(repo)` ile `summary_df` satırları `Durum` adına göre okunur; gecikme oranı hesaplanır; donut chart (Tamamlanan / Devam Eden); Geciken Seferler ayrı KPI ve oran; sıfıra bölme koruması; kaynak oran farkı için uyarı kaydı; hata durumunda genel mesaj
    - Router: giriş sonrası `TRANSPORT_OFFICE` ve `MATERIAL_RESPONSIBLE` için otomatik gösterim, `SUPPLIER` için gösterilmez; `summary_df` okuma izni kontrolü
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10_

  - [x] 8.3 Admin Panel'i yaz
    - `ui/admin_panel.py`: yalnızca aktif ADMIN için; kullanıcı listesi (şifre/özet yok), aktif/pasif anahtarı, rol ve kullanıcı bazlı tablo/fonksiyon izni verme-kaldırma; tüm işlemler `AdminService` üzerinden
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ]* 8.4 Dashboard ve UI için testler yaz
    - P11; `AppTest` ile giriş, rol bazlı görünürlük (SUPPLIER'da Dashboard yok), Admin Panel erişimi (ADMIN dışı reddedilir); dosya: `streamlit_client/tests/test_ui.py`, `test_dashboard.py`
    - _Requirements: 2.1, 4.1, 7.1, 7.2, 7.8_

- [x] 9. Mimari smoke testleri ve README
  - [ ]* 9.1 Modül sınırları ve yapılandırma smoke testlerini yaz
    - Alt çizgili iç öğelerin içe aktarılmaması; `bedrock_agentcore` kökünden içe aktarma olmaması; `.gitignore` içinde `Data/*.xlsx`; `agentcore.json` içinde runtime `agent` ve `UNIFIED_TRACES_DESTINATION_ENABLED`; `pyproject.toml` bağımlılık ayrımı; dosya: `app/agent/tests/test_architecture_smoke.py`
    - _Requirements: 8.1, 8.3, 8.8, 9.1_

  - [x] 9.2 `additionalPolicies` için politika dosyalarını hazırla
    - DynamoDB (users, permissions, kb tabloları ve indeksleri; en az ayrıcalık) ve Secrets Manager `GetSecretValue` için `app/agent/policies/*.json` dosyalarını yaz; `agentcore.json` içine eklemeyi Açık Karar 1 ile birlikte kullanıcı onayına bırak
    - _Requirements: 8.5, 8.6_

  - [x] 9.3 README'yi güncelle
    - Veri yükleme (`--dry-run` / `--apply`), tohumlama, yerel çalıştırma (8080 dışı bağlantı noktası), Admin Panel kullanımı, veri kalitesi bulguları özeti, dağıtım öncesi onay adımları
    - _Requirements: 10.1_

- [ ] 10. Dağıtım (kullanıcı onayıyla)
  - [~] 10.1 DynamoDB tablolarını oluştur, veriyi yükle ve dağıt
    - AWS kaynaklarını etkilediği için çalıştırmadan önce `user_input` ile açık onay al; onay yoksa görevi atla
    - Açık Karar 1 seçimini ve `agentcore.json` değişikliğini onayla; DynamoDB tablolarını oluştur; `ingest --apply`; `agentcore deploy`; IAM rollerini elle düzenleme
    - _Requirements: 8.5, 8.6, 8.7_

  - [~] 10.2 Dağıtım sonrası smoke testi
    - Geçerli kullanıcı ile `agentcore invoke --runtime agent --session-id <en az 33 karakter> --payload ...` ile altı Tool'dan en az ikisini çağır; yetkisiz ve pasif kullanıcı reddini doğrula; `agentcore logs runtime --tail`
    - _Requirements: 3.6, 5.10, 5.11_

- [x] 11. Final checkpoint - Tüm testlerin geçtiğinden emin ol
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Phase 2 uçtan uca testler (yerel, AWS kaynağı oluşturmadan)
  - [x] 12.1 Veri kaynağı testleri
    - Gerçek Excel'e karşı: tüm operasyonel sheet'lerin satır/kolon sayıları, `Functions` eşleşmeleri (fonksiyon-tablo-Keyid, kodla birebir), JSON kolonlarının parse edilmesi, malzeme/sefer/mip/supplier_code'un string ve baştaki sıfırların korunması, bozuk JSON enjeksiyonunda çökmeme
    - Operasyonel referans tarihi 2026-11-24: sistem saatine bağlı gecikme hesabı olmadığını doğrula (saat farklı bir tarihe sabitlenerek `get_delayed_truck`, `get_critical_part_status` ve Dashboard çıktılarının değişmediğini test et); kodda `datetime.now`/`date.today` ile gecikme türeten yer varsa düzelt
    - Dosya: `app/agent/tests/e2e/test_data_source.py`
    - _Requirements: 1.1, 1.3, 1.5, 1.6, 5.1, 7.6_

  - [x] 12.2 Kimlik doğrulama ve izin testleri
    - Dört rol için başarılı giriş (Excel'deki gerçek kullanıcılar, bellek içi depoya tohumlanır; şifre özetlenir), yanlış şifre, pasif kullanıcı, geçersiz ve süresi dolmuş token (sabit saat), logout, kilitleme
    - Başlangıçta tüm rollerin tüm operasyonel tablo ve fonksiyonlara erişimi; Admin yetkisiyle bir fonksiyonun yetkisini kaldırma, kullanıcının çalıştıramaması, yetkiyi geri verme; DynamoDB uyarlayıcıları üzerinden (Stubber/fake table) kalıcılık; normal kullanıcıların `AdminService` işlemlerine erişememesi; oturum/konuşma geçmişi izolasyonu (iki kullanıcı oturumu `st.session_state` ayrımı, başka kullanıcının token'ı ile geçmişe erişilememesi)
    - Dosya: `app/agent/tests/e2e/test_auth_permissions.py`, `streamlit_client/tests/e2e/test_session_isolation.py`
    - _Requirements: 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 3.2, 3.4, 3.7, 4.9, 5.10_

  - [x] 12.3 Tool testleri
    - Altı fonksiyon için Excel'deki gerçek Keyid ile: doğru parametre, yanlış parametre, eksik parametre, kayıt bulunamaması, birden fazla kayıt (ör. çok satırlı malzeme, çok duraklı sefer, birden fazla critical kaydı), yetkisiz erişim; `get_truck_route_info` sıralaması; beklenen sonuçlar Excel'den bağımsız hesaplanır
    - Dosya: `app/agent/tests/e2e/test_tools_e2e.py`
    - _Requirements: 5.1-5.14_

  - [x] 12.4 Doğal dil, konuşma bağlamı ve LLM entegrasyon testleri
    - Her fonksiyon için en az 5 Türkçe ve 5 İngilizce soru içeren veri kümesi (`app/agent/tests/e2e/nl_cases.py`); mock model ile araç seçimi/parametre çıkarımı testleri ve (varsa gerçek kimlik bilgileri ve `LOGISTIC_AI_MODEL_ID` ile) gerçek Bedrock modeli ile ayrı işaretli (`@pytest.mark.llm`) entegrasyon testleri; kimlik bilgisi yoksa BLOCKED olarak raporlanır; bu testler yalnızca model çağırır, AWS kaynağı oluşturmaz
    - Eksik Keyid'de ajanın bilgi istemesi; kullanıcının sonraki mesajda yalnızca Keyid göndermesi durumunda önceki konuşma bağlamıyla doğru fonksiyonun çalışması: bunun için istemci her çağrıda mevcut oturumun sohbet geçmişini payload'a ekler, backend geçmişi yalnızca bu istek için kullanır (kalıcı AgentCore Memory geliştirilmez); geçmiş boyutu ve içerik doğrulaması (yalnızca user/assistant metni, uzunluk sınırı)
    - Ajanın veri uydurmaması: araç sonucu `not_found`/`forbidden` iken yanıtta uydurma kayıt olmadığı kontrol edilir
    - _Requirements: 5.8, 5.9, 6.2, 6.3, 6.4_

  - [x] 12.5 Dashboard ve arayüz testleri
    - Dashboard KPI ve donut değerlerini Excel `summary_df` ile karşılaştır; yalnızca MATERIAL_RESPONSIBLE ve TRANSPORT_OFFICE için girişten sonra otomatik, SUPPLIER ve ADMIN için otomatik değil; "ilk giriş" davranışı: oturum başına yalnızca ilk görünümde otomatik, sonra gezinme ile
    - Streamlit `AppTest`: giriş, kullanıcı adı ve rol gösterimi, logout, sohbet geçmişi, "Yeni sohbet" düğmesi (yoksa ekle: geçmişi ve çalışma zamanı oturum kimliğini sıfırlar), Admin Panel (ADMIN dışı erişemez, izin verme/kaldırma)
    - Dosya: `streamlit_client/tests/e2e/test_dashboard_ui.py`
    - _Requirements: 2.1, 2.10, 4.1, 7.1-7.9_

  - [x] 12.6 TEST_REPORT.md'yi oluştur ve yerel çalıştırma komutlarını yaz
    - `Logistic_AI/TEST_REPORT.md`: her test için PASS/FAIL/NOT TESTED/BLOCKED, beklenen ve gerçekleşen sonuç, mock testler ile gerçek AWS/LLM entegrasyon testleri ayrı bölümlerde; başarısız testler düzeltilip yeniden çalıştırılır ve düzeltme notları eklenir; gerçek DynamoDB/AgentCore testleri kaynak oluşturulmadığı için NOT TESTED veya BLOCKED
    - README'ye yerel çalıştırma komutları (AWS kaynağı gerektirmeyen yerel mod: bellek içi depolar + Excel'den yükleme) eklenir; gerekirse yalnızca `LOGISTIC_AI_LOCAL_MODE=1` benzeri küçük bir yerel başlatma yolu eklenir, mevcut mimari değişmez
    - _Requirements: 8.4, 8.7, 10.1_

## Notes

- `*` ile işaretli görevler isteğe bağlıdır.
- Özellik testleri Hypothesis ile yazılır, en az 100 iterasyon çalışır ve `Feature: logistics-ai-data-agent, Property {numara}: {özellik metni}` etiketini taşır.
- Görev 10.1 kullanıcı onayı gerektirir; onay verilmezse 10.2 atlanır.
- Faz 1'in Cognito kodu (`cognito_service.py`, `TokenVerifier`) Açık Karar 1 sonuçlanana kadar silinmez.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1", "3.1", "4.1"] },
    { "id": 3, "tasks": ["2.2", "3.2", "4.2", "5.1"] },
    { "id": 4, "tasks": ["2.3", "3.3", "4.3", "5.2"] },
    { "id": 5, "tasks": ["3.4", "4.4", "5.3", "6.1", "6.2"] },
    { "id": 6, "tasks": ["6.3", "6.4"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 8, "tasks": ["8.4", "9.1", "9.2", "9.3"] },
    { "id": 9, "tasks": ["10.1"] },
    { "id": 10, "tasks": ["10.2", "12.1", "12.2", "12.3"] },
    { "id": 11, "tasks": ["12.4", "12.5"] },
    { "id": 12, "tasks": ["12.6"] }
  ]
}
```
