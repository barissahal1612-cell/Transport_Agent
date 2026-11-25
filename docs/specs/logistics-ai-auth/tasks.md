# Implementation Plan: logistics-ai-auth

## Overview

Bu plan, Logistics AI Assistant Faz 1 (Kullanıcı Kimlik Doğrulama ve Yetkilendirme) özelliğini `/home/participant/environment/Logistic_AI` klasöründe Python, Streamlit, boto3, PyJWT ve Strands/AgentCore ile adım adım uygulamak için hazırlanmıştır. Uygulama dili tasarımda belirtildiği gibi Python'dur (3.12+). Test araçları pytest ve Hypothesis'tir.

Mimari iki parçalıdır (bkz. design.md "Dağıtım Topolojisi"):

- **Agent_Backend**: `agentcore create --name LogisticAI --template agent-python-strands` ile oluşturulan iskelet (`Logistic_AI/agentcore/`, `Logistic_AI/app/agent/`). Proje dizini elle oluşturulmaz. `agentcore deploy` ile AgentCore_Runtime'a dağıtılır ve `customJWTAuthorizer` ile korunur.
- **Streamlit_Client**: `Logistic_AI/streamlit_client/` altında; AgentCore_Runtime üzerinde çalışmaz, ajanı HTTPS + `Authorization: Bearer` ile çağırır.
- **Shared_Auth_Package**: `Logistic_AI/app/agent/logistic_ai_shared_auth/` altında (CodeZip içinde); auth, authorization ve common modülleri burada yaşar. Streamlit_Client pakete `uv` yol bağımlılığı (editable) ile bağlanır.

Yaklaşım: önce AgentCore CLI iskeleti ve yapılandırma, sonra bağımlılığı olmayan saf çekirdek modüller (common, auth, authorization), ardından Agent_Backend, yerel dev doğrulaması, Streamlit config/session/UI, smoke testleri, dağıtım (kullanıcı onayıyla), dağıtım sonrası doğrulama ve README. Her özellik testi, ilgili uygulama görevinin hemen ardından gelir. `CustomerServiceAgent` projesi kapsam dışıdır. Bedrock model çağrıları, gerçek Tools, Skills, Memory ve MCP bileşenleri Faz 1'de eklenmez; Agent_Backend yalnızca deterministik Placeholder_Response döndürür.

Önemli kurallar:

- Yerel dev sunucusu daima `agentcore dev --port 8081` ile başlatılır; 8080 numaralı bağlantı noktası IDE tarafından kullanılır ve asla kullanılmaz veya durdurulmaz.
- Uzun süren süreçler (dev sunucusu, `streamlit run`) arka plan süreci olarak başlatılır.
- `agentcore deploy` AWS kaynaklarını etkilediğinden, çalıştırılmadan önce kullanıcıdan açık onay alınır.
- IAM rolleri elle düzenlenmez; ek izin gerekirse yalnızca `additionalPolicies` kullanılır.
- Shared_Auth_Package'ın `TokenVerifier` sınıfı, Streamlit `Settings` nesnesine bağımlı olmamalıdır; `user_pool_id`, `app_client_id` ve `region` değerlerini açık parametre olarak almalıdır (Agent_Backend bu değerleri kendi ortam değişkenlerinden okur).

## Tasks

- [x] 1. AgentCore CLI ile proje iskeletini oluştur ve yapılandır
  - [x] 1.1 `Logistic_AI` iskeletini `agentcore create` ile oluştur ve `agentcore.json` dosyasını yapılandır
    - `/home/participant/environment` dizininde `agentcore create --name LogisticAI --template agent-python-strands` komutunu çalıştır (AgentCore_CLI 1.0.3); çıktı klasörünü `Logistic_AI` olarak konumlandır (komut `LogisticAI/` üretirse klasörü `Logistic_AI` adına taşı veya yeniden adlandır, `.git` bütünlüğünü koru); proje dizinini elle oluşturma
    - Oluşan yapıyı doğrula: `agentcore/agentcore.json`, `app/agent/main.py`, `app/agent/parse.py`, `app/agent/model/load.py`, `app/agent/memory/session.py`, `app/agent/pyproject.toml`, `app/agent/tests/`
    - `agentcore.json` içinde adı `agent` olan tam olarak bir runtime bırak; şablonun getirdiği `agentMemory` tanımını kaldır (Memory Faz 1'de oluşturulmaz)
    - `agent` runtime'ının `envVars` listesine `{ "name": "UNIFIED_TRACES_DESTINATION_ENABLED", "value": "true" }` ekle
    - `agent` runtime'ına `customJWTAuthorizer` ekle: Cognito discovery URL'si (`https://cognito-idp.{region}.amazonaws.com/{poolId}/.well-known/openid-configuration`) ve izin verilen tek App Client kimliği (`allowedClients`); gerçek değerler Cognito kurulumundan sonra doldurulacağından yer tutucu kullan ve README'de belgele. Dikkat: bu değerler ve Agent_Backend'in `LOGISTIC_AI_USER_POOL_ID`, `LOGISTIC_AI_APP_CLIENT_ID`, `LOGISTIC_AI_AWS_REGION` ortam değişkenleri sürüm kontrolüne gerçek değerle girmemelidir (Req 8.1); dağıtım öncesi yerelde doldurulacak şekilde yer tutucularla bırak
    - `additionalPolicies` alanını yalnızca gerekirse kullan (Faz 1'de ek izin gerekmez); IAM rolünü elle düzenleme
    - _Requirements: 11.1, 11.2, 11.3, 12.5, 13.2, 13.3, 13.11_

  - [x] 1.2 `.gitignore`, `.env.local` işleme, izin tablosu ve paket iskeletlerini oluştur
    - `Logistic_AI/.gitignore` dosyasını güncelle (mevcutlara ek): `.env*`, `.env.local`, `__pycache__`, `.venv`, `.pytest_cache`; `agentcore/.env.local` zaten ignore edilmiş olmalı, doğrula
    - `Logistic_AI/config/permissions.json` oluştur: üç rol (`SUPPLIER`, `MATERIAL_RESPONSIBLE`, `TRANSPORT_OFFICE`) için boş izin kümeleri ve `"version": 1`
    - `app/agent/pyproject.toml` güncelle: `[project].dependencies` yalnızca çalışma zamanı paketleri (`PyJWT[crypto]`, `boto3` ve şablonun getirdikleri; ARM64 Linux wheel'i olanlar); `pytest` ve `hypothesis` yalnızca `[dependency-groups].dev` altında
    - `app/agent/logistic_ai_shared_auth/{auth,authorization,common}` paket klasörlerini ve `__init__.py` dosyalarını oluştur (Shared_Auth_Package, design.md "Shared_Auth_Package konumlandırma kararı", Seçenek B)
    - `streamlit_client/` iskeletini oluştur: `app.py` (boş giriş noktası), `pyproject.toml` (bağımlılıklar `streamlit`, `requests`, `PyJWT[crypto]`; `logistic_ai_shared_auth` için `path = "../app/agent/logistic_ai_shared_auth"`, editable; dev grubu `pytest`, `hypothesis`), `logistic_ai/{config,session,ui}/__init__.py`, `tests/`
    - _Requirements: 8.3, 9.1, 9.7, 9.8, 9.9, 11.5, 11.6_

- [x] 2. Shared_Auth_Package: ortak denetim ve günlük altyapısını uygula
  - [x] 2.1 `Clock`, `errors`, `build_audit_record`, `AuditLogger`, `JsonAuditLogger`, `SanitizingFilter` ve `safe_error_message` yaz
    - `logistic_ai_shared_auth/common/clock.py`: `Clock` protokolü, sistem saati ve test için sabit saat
    - `logistic_ai_shared_auth/common/errors.py`: ortak istisna türleri ve `safe_error_message()`; ayrıntı zaman damgasıyla günlüğe gitsin
    - `logistic_ai_shared_auth/common/audit.py`: saf `build_audit_record` (UTC ISO-8601, kullanıcı adı en fazla 255 karakter, yasaklı anahtarlar kayda girmez); `JsonAuditLogger` ayrı `logistic_ai.audit` logger'ına yazar, yazma hatasında en fazla 3 deneme, sonra hata günlüğüne kayıt; kimlik doğrulama sonucunu değiştirmez
    - `logistic_ai_shared_auth/common/log_sanitizer.py`: JWT biçimli dizeleri, `password=`, `token=`, `secret=` desenlerini ve bilinen sırları maskele
    - _Requirements: 4.5, 6.2, 8.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 12.7_

  - [ ]* 2.2 Denetim kaydı için özellik testi yaz
    - **Property 12: Denetim kayıtları gerekli alanları içerir ve sır içermez**
    - Dosya: `app/agent/tests/test_prop_audit_record.py`
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.6**

  - [ ]* 2.3 Günlük sızıntısı için özellik testi yaz
    - **Property 13: Günlük çıktısı sır içermez**
    - Dosya: `app/agent/tests/test_prop_log_sanitizer.py`
    - **Validates: Requirements 6.2, 8.6, 10.6**

  - [ ]* 2.4 Genel hata mesajı için özellik testi yaz
    - **Property 20: Beklenmeyen hatalar kullanıcıya genel mesajla sunulur**
    - Dosya: `app/agent/tests/test_prop_safe_error.py`
    - **Validates: Requirements 10.4**

  - [ ]* 2.5 Denetim yazıcısı yeniden deneme için birim testi yaz
    - Yazma 3 kez başarısız olduğunda hata günlüğüne kayıt yapıldığını ve işlem sonucunun değişmediğini doğrula
    - Dosya: `app/agent/tests/test_audit_retry.py`
    - _Requirements: 10.5_

- [x] 3. Shared_Auth_Package: Auth modülünü uygula
  - [x] 3.1 `AuthService` soyut arayüzünü, veri türlerini ve `validate_credentials` fonksiyonunu yaz
    - `logistic_ai_shared_auth/auth/service.py`: `AuthService(ABC)` (`authenticate`, `refresh`, `revoke`), `TokenSet`, `AuthResult`
    - `logistic_ai_shared_auth/auth/errors.py`: `AuthErrorKind`, `AuthError` (sabit genel Türkçe kullanıcı mesajları, `invalid_fields`)
    - `validate_credentials`: kullanıcı adı 1-64, şifre 1-128 karakter; yalnızca boşluk boş sayılır
    - _Requirements: 1.3, 1.5, 2.3, 9.2, 9.8_

  - [x] 3.2 `LoginAttemptTracker` yerel kilitlemeyi yaz
    - `logistic_ai_shared_auth/auth/lockout.py`: kullanıcı adı başına (küçük harf, kırpılmış) ardışık başarısızlık sayacı, 5 başarısızlıkta kilit, enjekte edilen `Clock` ile 15 dakika kilit süresi
    - Başarılı girişte sayacı sıfırla
    - _Requirements: 2.7_

  - [x] 3.3 `MockAuthService` uygulamasını yaz
    - `logistic_ai_shared_auth/auth/mock_service.py`: programlanabilir sonuçlar ve çağrı sayacı, ağ çağrısı yok
    - _Requirements: 9.2_

  - [x] 3.4 `CognitoAuthService` uygulamasını yaz
    - `logistic_ai_shared_auth/auth/cognito_service.py`: `boto3` `cognito-idp`, `USER_PASSWORD_AUTH`, bağlantı/okuma zaman aşımı ile toplam 5 saniye sınırı, `max_attempts=1`
    - Hata eşleme: `INVALID_CREDENTIALS`, `LOCKED_OUT`, `NEW_PASSWORD_REQUIRED` (token iletilmez), `SERVICE_UNAVAILABLE` (ayrıntı yalnızca günlükte)
    - `refresh` (`REFRESH_TOKEN_AUTH`) ve `revoke` (`RevokeToken`) metotlarını ekle; Cognito çağrısından önce `validate_credentials` ve `LoginAttemptTracker` kontrolü yap
    - `endpoint_url` yalnızca `https://` olabilir; aksi hâlde veri göndermeden bağlantı hatası döndür
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 7.3, 8.7, 8.8_

  - [ ]* 3.5 Geçersiz kimlik bilgileri için özellik testi yaz
    - **Property 1: Geçersiz kimlik bilgileri Cognito'ya gönderilmez**
    - Dosya: `app/agent/tests/test_prop_credentials_validation.py`
    - **Validates: Requirements 1.3, 1.5, 2.3**

  - [ ]* 3.6 Hata eşleme için özellik testi yaz
    - **Property 2: Kimlik doğrulama hataları genel mesaja eşlenir ve token sızdırmaz**
    - Dosya: `app/agent/tests/test_prop_auth_error_mapping.py`
    - **Validates: Requirements 2.4, 2.5, 2.6**

  - [ ]* 3.7 Yerel kilitleme için özellik testi yaz
    - **Property 3: Ardışık başarısızlıklardan sonra yerel kilitleme**
    - Dosya: `app/agent/tests/test_prop_lockout.py`
    - **Validates: Requirements 2.7**

  - [ ]* 3.8 `CognitoAuthService` için `botocore.stub.Stubber` birim testleri yaz
    - Başarılı giriş, `NEW_PASSWORD_REQUIRED`, `RevokeToken` çağrısı ve `http://` uç noktasının reddi senaryoları
    - Dosya: `app/agent/tests/test_cognito_service.py`
    - _Requirements: 2.2, 2.6, 7.3, 8.8_

- [x] 4. Shared_Auth_Package: Authorization modülünü uygula
  - [x] 4.1 `Role` ve `resolve_role` fonksiyonunu yaz
    - `logistic_ai_shared_auth/authorization/roles.py`: `Role` enum'u (tam ve büyük/küçük harf duyarlı eşleşme), `RoleResolutionError` (`NO_ROLE`, `MULTIPLE_ROLES`), `VerifiedIdentity`
    - Geçersiz grup adlarını ve tekrarları yok say; tek farklı geçerli rol varsa onu döndür
    - _Requirements: 3.1, 3.5, 3.6, 3.8_

  - [x] 4.2 `TokenVerifier` ve `resolve_identity` fonksiyonlarını yaz
    - `logistic_ai_shared_auth/authorization/token_verifier.py`: `PyJWKClient` tabanlı `SigningKeyProvider` (önbellek, bilinmeyen `kid` için bir kez yenileme), `RS256`; `user_pool_id`, `app_client_id`, `region` açık parametre olarak alınır (Streamlit `Settings`'e bağımlılık yok)
    - `exp`, `iss`, `aud` ve `token_use` doğrula; eksik veya okunamayan token'ı `TokenVerificationError` ile reddet; ID_Token ve Agent_Backend'e gelen Bearer token türleri için `token_use` beklentisi parametrik olsun (Streamlit tarafı `id`, AgentCore'a gönderilen token'ın türü design.md Açık Soru 2 ve Cognito `allowedClients` davranışına göre doğrulanmalıdır)
    - `resolve_identity(id_token)`: önce `verify`, sonra `resolve_role`; rolü yalnızca doğrulanmış `cognito:groups` talebinden türet
    - _Requirements: 3.2, 3.3, 3.4, 3.7, 13.9_

  - [x] 4.3 `PermissionTable` sınıfını yaz
    - `logistic_ai_shared_auth/authorization/permission_table.py`: değişmez tablo, `from_mapping`, `load(path)`, `with_definition`, `permissions_for`
    - Ad doğrulaması: boş olamaz, 64 karakteri aşamaz, mevcut rol adıyla aynı olamaz, rol içinde tekrarlı izin olamaz; `PermissionTableError` ile reddet ve mevcut tabloyu koru
    - Dosya yüklenemez veya geçersizse uygulama başlamasın (güvenli başarısızlık)
    - _Requirements: 4.1, 9.3, 9.4_

  - [x] 4.4 `Authorizer`, `Decision` ve `PermissionDenied` yapılarını yaz
    - `logistic_ai_shared_auth/authorization/authorizer.py`: `authorize(username, role, permission)` saf karar, varsayılan olarak reddet
    - Ret durumunda `AuditLogger.log_authorization_denied` çağır; denetim istisnasını yut ve ret sonucunu koru
    - `require(ctx, permission)`: reddedilirse "Bu işlem için yetkiniz yok" ile `PermissionDenied` fırlat
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ]* 4.5 Rol çözümleme için özellik testi yaz
    - **Property 5: Rol çözümleme tek geçerli rolü kesin kurallarla belirler**
    - Dosya: `app/agent/tests/test_prop_resolve_role.py`
    - **Validates: Requirements 3.1, 3.2, 3.5, 3.6, 3.8, 5.7**

  - [ ]* 4.6 Token doğrulama için özellik testi yaz
    - **Property 4: Kusurlu ID_Token her zaman reddedilir**
    - Dosya: `app/agent/tests/test_prop_token_verifier.py` (testte üretilen RSA anahtarı ile JWT imzala)
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 4.7 İzin tablosu gidiş-dönüş için özellik testi yaz
    - **Property 9: İzin tablosu yapılandırma ile değişir ve gidiş-dönüş korunur**
    - Dosya: `app/agent/tests/test_prop_permission_roundtrip.py`
    - **Validates: Requirements 4.1, 9.3**

  - [ ]* 4.8 Geçersiz izin tanımları için özellik testi yaz
    - **Property 10: Geçersiz izin tanımları tabloyu değiştirmez**
    - Dosya: `app/agent/tests/test_prop_permission_invalid_definition.py`
    - **Validates: Requirements 9.4**

  - [ ]* 4.9 Yetki kararlarının determinizmi için özellik testi yaz
    - **Property 7: Yetki kararları deterministiktir**
    - Dosya: `app/agent/tests/test_prop_authorizer_deterministic.py`
    - **Validates: Requirements 4.2, 4.8**

  - [ ]* 4.10 Varsayılan ret için özellik testi yaz
    - **Property 8: Varsayılan olarak reddet ve reddedilen istek yan etki oluşturmaz**
    - Dosya: `app/agent/tests/test_prop_authorizer_deny.py`
    - **Validates: Requirements 4.3, 4.4**

  - [ ]* 4.11 Yetki ret kaydı için özellik testi yaz
    - **Property 11: Yetki ret kaydı gerekli alanları içerir ve yazma hatası kararı değiştirmez**
    - Dosya: `app/agent/tests/test_prop_authz_audit.py`
    - **Validates: Requirements 4.5, 4.6**

- [~] 5. Checkpoint - Shared_Auth_Package testleri
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Agent_Backend'i uygula (`Logistic_AI/app/agent`)
  - [x] 6.1 `parse.py` içinde `parse_payload` fonksiyonunu yaz
    - Şablonun ürettiği `parse.py` dosyasını koru ve gerekirse uyarla: istek yükünden `prompt` ve `actorId` alanlarını oku
    - `prompt` yoksa, `None` ise veya yalnızca boşluktan oluşuyorsa model/ajan çağrılmadan doğrulama hatası döndür; `actorId` bilgilendirme amaçlıdır ve rol kaynağı değildir
    - Tüm fonksiyon imzalarında tür ipuçları kullan
    - _Requirements: 11.4, 11.10, 11.11_

  - [x] 6.2 Genişletme noktalarını işlevsiz stub olarak oluştur
    - `app/agent/model/load.py`: Faz 1'de Bedrock çağrısı yapmayan stub; gelecekteki model kimliğinin `global.` önekli inference profile biçiminde ve dağıtım zamanında `aws bedrock list-foundation-models --by-provider Anthropic` (ACTIVE) çıktısından seçileceğini belgeleyen docstring, model kimliği sabiti yok
    - `app/agent/tools/__init__.py` (boş paket), `app/agent/prompts/__init__.py` ve `app/agent/prompts/system_prompt.py` (stub), `app/agent/memory/session.py` (stub/devre dışı; `agentMemory` kullanılmaz)
    - Şablonun `main.py` ve diğer dosyalarında `agentMemory` veya Bedrock çağrısına yönelik referansları kaldır veya devre dışı bırak
    - _Requirements: 9.7, 12.4, 12.5, 12.6_

  - [x] 6.3 Placeholder_Response üreten Strands ajan iskeletini yaz
    - `app/agent/placeholder_agent.py`: Strands ajan iskeleti (veya uyumlu ince sarmalayıcı); Amazon Bedrock modelini çağırmadan tüm geçerli `prompt` değerleri için aynı sabit Placeholder_Response metnini asenkron parçalar hâlinde üretir
    - Ajan oluşturma fonksiyonu modül yüklenirken değil, çağrıldığında çalışmalıdır (lazy init için)
    - Kullanıcı mesajlarını, token'ları ve şifreleri günlüğe yazma
    - _Requirements: 12.1, 12.2, 12.3, 12.7_

  - [x] 6.4 `main.py` giriş noktasını yaz ve yetkilendirmeyi bağla
    - `from bedrock_agentcore.runtime import BedrockAgentCoreApp` kullan (paket kökünden içe aktarma yok); `@app.entrypoint` ile süslenmiş async generator işleyici; `__main__` bloğunda `app.run()`
    - `_get_agent()` ile ajanı ilk istekte oluştur (lazy initialization); modül yüklenirken ajan kurma
    - Akış: `parse_payload` → hata varsa ajan çalıştırmadan doğrulama hatası → `Authorization` başlığındaki Bearer token'ı `Shared_Auth_Package.TokenVerifier` ile yeniden doğrula → `resolve_role` yalnızca doğrulanmış `cognito:groups` talebinden → `Authorizer.authorize` (deny-by-default, Faz 1'de izin tablosu boş olduğundan sohbet izni için tablo yapılandırması gerekir; izin adı `chat:invoke`) → reddedilirse "Bu işlem için yetkiniz yok" ve Requirement 4.5 denetim kaydı → izinliyse Placeholder_Response
    - Payload'daki (`actorId` dahil) hiçbir alanı rol kaynağı olarak kullanma
    - `PermissionTable.load` ve `TokenVerifier` yapılandırmasını ortam değişkenlerinden (`LOGISTIC_AI_USER_POOL_ID`, `LOGISTIC_AI_APP_CLIENT_ID`, `LOGISTIC_AI_AWS_REGION`, `LOGISTIC_AI_PERMISSIONS_FILE`) oku; `SanitizingFilter`'ı uygula
    - `agentcore/agentcore.json` içinde `Authorization` başlığının işleyiciye iletilmesi için `requestHeaderAllowlist` ayarını ekle; CLI 1.0.3 şemasını `agentcore --help` / dokümantasyon ile doğrula (design.md Açık Soru 2'yi kapat) ve sonucu `app/agent/README.md` veya bu görevin notlarına yaz
    - _Requirements: 3.7, 4.5, 4.7, 11.7, 11.8, 11.9, 12.1, 12.2, 12.7, 13.9, 13.10_

  - [ ]* 6.5 Payload gidiş-dönüşü için özellik testi yaz
    - **Property 21: Payload ayrıştırma gidiş-dönüşü korur**
    - Dosya: `app/agent/tests/test_prop_parse_roundtrip.py`
    - **Validates: Requirements 11.12**

  - [ ]* 6.6 Boş prompt reddi için özellik testi yaz
    - **Property 22: Boş veya eksik prompt ajanı çalıştırmadan reddedilir**
    - Dosya: `app/agent/tests/test_prop_empty_prompt.py`
    - **Validates: Requirements 11.11**

  - [ ]* 6.7 Yer tutucu yanıt determinizmi için özellik testi yaz
    - **Property 23: Yer tutucu yanıt determinist ve Bedrock çağrısı yapmaz**
    - Dosya: `app/agent/tests/test_prop_placeholder.py` (Bedrock istemcisi yerine çağrı sayacı tutan test çifti)
    - **Validates: Requirements 12.2, 12.3**

  - [ ]* 6.8 Agent_Backend rol türetme için özellik testi yaz
    - **Property 24: Agent_Backend rolü yalnızca doğrulanmış token talebinden türetir**
    - Dosya: `app/agent/tests/test_prop_agent_role_source.py` (sahte `RequestContext`, testte imzalanmış JWT, payload'a ve özel başlıklara enjekte edilen sahte roller)
    - **Validates: Requirements 3.7, 13.9**

  - [ ]* 6.9 Agent_Backend yetkilendirme bağımsızlığı için özellik testi yaz
    - **Property 25: Agent_Backend yetkilendirmesi Streamlit_Client kontrolünden bağımsızdır**
    - Dosya: `app/agent/tests/test_prop_agent_authz.py`
    - **Validates: Requirements 4.7, 13.10**

  - [ ]* 6.10 Agent_Backend birim testlerini yaz
    - Placeholder_Response, doğrulama hatası ve yetkisiz erişim yolları; modül içe aktarıldıktan sonra `_agent is None` (lazy init); `bedrock_agentcore.runtime`'dan içe aktarma (statik kontrol)
    - Dosya: `app/agent/tests/test_agent_main.py`
    - _Requirements: 11.7, 11.8, 12.8_

- [x] 7. Yerel geliştirme doğrulaması
  - [x] 7.1 Yerel dev doğrulama betiğini yaz ve çalıştır
    - `Logistic_AI/scripts/local_dev_check.sh` oluştur: 8080 numaralı bağlantı noktasını kullanmayı veya durdurmayı reddeden koruma içersin; `agentcore dev --port 8081` sunucusunu başlatır (başsız), hazır olmasını bekler, ikinci adımda `agentcore invoke --runtime agent --local --port 8081 --payload '{"prompt":"Merhaba"}'` çağırır ve yalnızca bu betiğin başlattığı süreci temizler
    - Dev sunucusunu `control_bash_process` ile arka plan süreci olarak başlat, `agentcore invoke ... --local` komutunu ayrı bir komutta çalıştır; 8081 doluysa `agentcore dev --port 8082` kullan; asla 8080 kullanma
    - Yerel çağrıda JWT yoksa yetkisiz yanıt (veya yerel dev modunda kimlik doğrulama davranışı) beklendiği gibi olduğunu ve geçerli yükte yer tutucu yanıt/yetkisiz yanıt akışının hatasız döndüğünü doğrula; sonucu not et
    - _Requirements: 11.9, 12.2, 14.6_

- [x] 8. Streamlit_Client: Config modülünü uygula
  - [x] 8.1 `Settings`, `ConfigError`, `load_settings` ve `parse_idle_timeout` fonksiyonlarını yaz
    - `streamlit_client/logistic_ai/config/settings.py` içinde zorunlu ortam değişkenlerini oku: `LOGISTIC_AI_USER_POOL_ID`, `LOGISTIC_AI_APP_CLIENT_ID`, `LOGISTIC_AI_AWS_REGION`, `LOGISTIC_AI_AGENT_RUNTIME_ARN`
    - İsteğe bağlı değerler: `LOGISTIC_AI_IDLE_TIMEOUT_MINUTES`, `LOGISTIC_AI_PERMISSIONS_FILE`, `cognito_endpoint_url` (yalnızca `https://`)
    - Eksik veya boş değerler için yalnızca değişken adlarını taşıyan `ConfigError` fırlat
    - İsteğe bağlı `SecretFetcher` soyutlamasını ekle; 10 saniye zaman aşımı veya erişim hatasında "Secret_Store erişim hatası" ile başlatmayı reddet
    - `parse_idle_timeout`: yalnızca 1-480 aralığındaki tamsayıları kabul et, diğer her durumda 30 döndür
    - _Requirements: 6.8, 6.9, 8.1, 8.4, 8.5_

  - [ ]* 8.2 Eksik yapılandırma için özellik testi yaz
    - **Property 19: Eksik yapılandırma yalnızca değişken adlarını bildirir**
    - Dosya: `streamlit_client/tests/test_prop_config_missing.py`
    - **Validates: Requirements 8.1, 8.4**

  - [ ]* 8.3 Boşta kalma süresi yapılandırması için özellik testi yaz
    - **Property 17: Boşta kalma süresi yapılandırması sınırlar içinde kalır**
    - Dosya: `streamlit_client/tests/test_prop_idle_timeout_config.py`
    - **Validates: Requirements 6.8, 6.9**

  - [ ]* 8.4 Secret_Store hata durumları için birim testleri yaz
    - Zaman aşımı, erişim hatası ve boş değer senaryolarını test et; hata mesajının değer içermediğini doğrula
    - Dosya: `streamlit_client/tests/test_config_secret_store.py`
    - _Requirements: 8.4, 8.5_

- [x] 9. Streamlit_Client: Session modülünü ve AgentCore_Client'ı uygula
  - [x] 9.1 `SessionManager` sınıfını yaz
    - `streamlit_client/logistic_ai/session/manager.py`: `establish`, `touch`, `require_valid_session`, `logout`, `is_authenticated`; oturum deposu `MutableMapping` (üretimde `st.session_state`)
    - Token'ları ve kimliği yalnızca sunucu tarafı depoda sakla; şifreyi hiç saklama
    - Doğrulama sırası: token varlığı, boşta kalma süresi (zaman aşımı kaydı), access token süresi, kalan süre ≤ 300 saniye ise en fazla bir yenileme denemesi (10 saniye zaman aşımı); başarısızlıkta tüm oturumu sil
    - Yenilemeden sonra yeni ID_Token'ı yeniden doğrula, rol değiştiyse oturumu reddet
    - AgentCore 401/403 sonrası yenileme için aynı kuralları kullanan bir `refresh_for_agent_call()` yardımcısı sun (Requirement 6.3 kuralları: en fazla 1 deneme)
    - `logout`: önce yerel veriyi sil (token'lar, kullanıcı adı, rol, sohbet içeriği), sonra `AuthService.revoke` (10 saniye zaman aşımı); hata durumunda günlüğe yaz ve yine de devam et; çıkış denetim kaydı yaz
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.2, 7.3, 7.5, 10.2, 10.3, 13.7_

  - [x] 9.2 `UserContextProvider` ve `UserContext` yapılarını yaz
    - `streamlit_client/logistic_ai/session/user_context.py`: `current()` geçerli oturumda `UserContext(username, role)` döndürür; aksi hâlde `NotAuthenticated` fırlatır ve hiçbir kullanıcı adı veya rol sızdırmaz
    - _Requirements: 9.5, 9.6_

  - [x] 9.3 `AgentCoreClient` sınıfını yaz
    - `streamlit_client/logistic_ai/session/agentcore_client.py`: URL `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{quote(runtime_arn, safe='')}/invocations?qualifier=DEFAULT`
    - Başlıklar: `Authorization: Bearer {access_token}`, `Content-Type: application/json`, `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` (en az 33 karakter; kısaysa güvenli şekilde üret/doldur); gövde `{"prompt": ..., "actorId": ...}`
    - Yalnızca HTTPS; SigV4/`boto3` kullanma; genel zaman aşımı 30 saniye; `HttpTransport` soyutlaması ile test edilebilir
    - 401/403 → `AgentCoreUnauthorized`; ağ hatası/zaman aşımı → teknik ayrıntı içermeyen genel hata (ayrıntı günlükte)
    - _Requirements: 13.5, 13.6, 13.7, 13.8, 10.4_

  - [ ]* 9.4 Oturum geçerliliği için özellik testi yaz
    - **Property 14: Oturum geçerliliği yalnızca token varlığı, süre ve boşta kalmaya bağlıdır**
    - Dosya: `streamlit_client/tests/test_prop_session_validity.py`
    - **Validates: Requirements 6.5, 6.6, 7.7, 9.5, 9.6**

  - [ ]* 9.5 Token yenileme kararı için özellik testi yaz
    - **Property 15: Token yenileme kararı kalan süreye bağlıdır ve en fazla bir kez denenir**
    - Dosya: `streamlit_client/tests/test_prop_session_refresh.py`
    - **Validates: Requirements 6.3, 6.4**

  - [ ]* 9.6 Boşta kalma zaman aşımı için özellik testi yaz
    - **Property 16: Boşta kalma zaman aşımı yapılandırılan süreyle sınırlıdır**
    - Dosya: `streamlit_client/tests/test_prop_session_idle.py`
    - **Validates: Requirements 6.7, 10.3**

  - [ ]* 9.7 Çıkış için özellik testi yaz
    - **Property 18: Çıkış tüm oturum verisini siler**
    - Dosya: `streamlit_client/tests/test_prop_logout.py`
    - **Validates: Requirements 7.2, 7.5, 7.7**

  - [ ]* 9.8 Rolün yalnızca doğrulanmış token'dan türetilmesi için özellik testi yaz
    - **Property 6: Rol yalnızca doğrulanmış token'dan türetilir**
    - Dosya: `streamlit_client/tests/test_prop_role_source.py`
    - **Validates: Requirements 3.2, 3.7**

  - [ ]* 9.9 `AgentCoreClient` için birim testleri yaz
    - Sahte HTTP taşıyıcısıyla URL biçimi, başlıklar, 33+ karakter oturum kimliği, 401/403 sonrası tek yenileme denemesi ve başarısızlıkta Login_Screen yönlendirmesi, ağ hatası/zaman aşımında genel mesaj
    - Dosya: `streamlit_client/tests/test_agentcore_client.py`
    - _Requirements: 13.5, 13.6, 13.7, 13.8_

- [x] 10. Streamlit_Client: UI modülünü uygula ve bileşenleri bağla
  - [x] 10.1 `router.render()` fonksiyonunu yaz
    - `streamlit_client/logistic_ai/ui/router.py`: her yeniden çalıştırmada önce `SessionManager.require_valid_session()` çağır; başarısızsa Login_Screen, başarılıysa Chatbot_Home_Screen göster
    - Doğrudan erişim ve rol belirsizliği durumunda ana ekran içeriğini göstermeden Login_Screen'e yönlendir; oturum sonu hata mesajını göster
    - Tüm beklenmeyen istisnaları `safe_error_message()` ile genel mesaja çevir
    - _Requirements: 5.1, 5.6, 5.7, 6.6, 7.6, 7.7, 10.4_

  - [x] 10.2 Login_Screen'i yaz
    - `streamlit_client/logistic_ai/ui/login_screen.py`: üstte "Logistics AI Assistant" başlığı; `st.form` içinde tam olarak üç öğe: kullanıcı adı (`max_chars=64`), maskeli şifre (`max_chars=128`), giriş butonu
    - Girdiyi `validate_credentials` ile doğrula; eksik alanı belirten hata göster, istek gönderme
    - İstek sürerken butonu devre dışı bırak, 200 ms içinde `st.spinner` göster, `in_flight` bayrağıyla ikinci isteği engelle; genel istek zaman aşımı 30 saniye
    - Başarıda sırayla `AuthService.authenticate`, `resolve_identity`, `SessionManager.establish`, giriş denetim kaydı; rol hatalarında oturum oluşturma ve uygun mesajı göster
    - Hatada şifre alanını temizle, kullanıcı adını koru
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 3.5, 3.6, 10.1_

  - [x] 10.3 Chatbot_Home_Screen'i yaz
    - `streamlit_client/logistic_ai/ui/home_screen.py`: üstte tam kullanıcı adı (en fazla 64 karakter) ve rol, sayfa kaydırılmadan görünen çıkış butonu, ilk açılışta boş sohbet geçmişi alanı, tek mesaj giriş alanı
    - Yapay zekâ yanıtlarının henüz kullanılamadığını belirten kalıcı bilgi mesajı
    - Mesaj gönderimi `AgentCoreClient.invoke` ile yapılır: `Authorization: Bearer` ve 33+ karakterli oturum kimliği; Placeholder_Response veya "Bu işlem için yetkiniz yok" yanıtı sohbet alanında gösterilir; `AgentCoreUnauthorized` durumunda `SessionManager` ile en fazla bir kez yenileme dene, başarısızsa Login_Screen'e yönlendir; ağ hatası/zaman aşımında genel hata mesajı
    - Çıkış butonu `SessionManager.logout` çağırır ve Login_Screen'e yönlendirir
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 7.1, 7.2, 7.4, 13.5, 13.6, 13.7, 13.8_

  - [x] 10.4 `app.py` giriş noktasını yaz ve bileşenleri bağla
    - `load_settings` ile yapılandırmayı yükle; `ConfigError` durumunda yalnızca eksik değişken adlarını yazıp sıfır olmayan çıkış koduyla sonlan
    - `PermissionTable.load`, `CognitoAuthService`, `TokenVerifier`, `Authorizer`, `SessionManager`, `UserContextProvider`, `AgentCoreClient`, `JsonAuditLogger` ve `SanitizingFilter` nesnelerini oluştur ve `router.render()` çağır
    - İzin tablosu yüklenemezse uygulamayı başlatma
    - Streamlit_Client barındırma hedefini (yerel/konteyner) zorunlu kılma
    - _Requirements: 8.1, 8.4, 8.5, 8.6, 9.1, 9.2, 9.5, 9.7, 13.12_

  - [ ]* 10.5 UI için Streamlit `AppTest` birim testleri yaz
    - Login_Screen: başlık, üç öğe, maskeli şifre, hata sonrası şifre temizleme ve kullanıcı adı korunması, boş alan hataları (`MockAuthService` ile)
    - Chatbot_Home_Screen: kullanıcı adı, rol, boş sohbet alanı, bilgi mesajı, çıkış butonu
    - Yönlendirme: kimliği doğrulanmamış doğrudan erişim, çıkış sonrası geri gezinme, yetkilendirmenin korumalı işlevden önce çağrılması
    - Dosya: `streamlit_client/tests/test_ui.py`
    - _Requirements: 1.2, 1.4, 1.5, 1.6, 4.2, 4.7, 5.2, 5.3, 5.4, 5.5, 5.6, 7.1, 7.6_

- [~] 11. Checkpoint - Agent_Backend ve Streamlit_Client testleri
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Mimari ve yapılandırma smoke testleri
  - [ ]* 12.1 Modül sınırları ve yapılandırma smoke testlerini yaz
    - Hiçbir modülün başka bir modülün alt çizgi ile başlayan iç öğelerini içe aktarmadığını; `bedrock`, `mcp` içe aktarımı ve gerçek Tools/Skills olmadığını; `bedrock_agentcore` paket kökünden içe aktarma yapılmadığını doğrula
    - Varsayılan `config/permissions.json` dosyasında üç rolün tanımlı ve izin kümelerinin boş olduğunu doğrula
    - `.gitignore` içinde `.env.local` kuralının bulunduğunu doğrula
    - `agentcore/agentcore.json`: adı `agent` olan tam bir runtime, `agentMemory` yok, `envVars` içinde `UNIFIED_TRACES_DESTINATION_ENABLED=true`, `customJWTAuthorizer` tanımı, `additionalPolicies` dışında elle IAM düzenlemesi yok
    - `app/agent/pyproject.toml`: `[project].dependencies` içinde `pytest`/`hypothesis` yok, `[dependency-groups].dev` içinde var
    - Dosya: `app/agent/tests/test_architecture_smoke.py`
    - _Requirements: 8.3, 9.1, 9.7, 9.9, 11.3, 11.5, 11.7, 12.5, 13.2, 13.3, 13.11_

- [ ] 13. Dağıtım ve dağıtım sonrası doğrulama
  - [ ] 13.1 Kullanıcı onayıyla `agentcore deploy` çalıştır
    - AWS kaynaklarını etkilediğinden, komutu çalıştırmadan önce `user_input` ile kullanıcıdan açık onay al; onay yoksa görevi atla ve bekleyen olarak bırak
    - Ön kontroller: `aws sts get-caller-identity`, `customJWTAuthorizer` değerlerinin (discovery URL ve `allowedClients`) gerçek Cognito User Pool ve App Client ile eşleştiği (kullanıcı değerleri sağlar; sürüme eklenmez), tüm testlerin geçtiği
    - Onaydan sonra `Logistic_AI` dizininde `agentcore deploy` çalıştır (ilk dağıtım yaklaşık 5-8 dakika); sorun olursa `agentcore --debug deploy` ile ayrıntı al; IAM rollerini elle düzenleme
    - Anthropic model erişimi hatası görülürse bunun Faz 1'de beklenmediğini (Bedrock çağrısı yok) not et
    - _Requirements: 13.1, 13.2, 13.3, 13.11_

  - [~] 13.2 Dağıtım sonrası smoke testini `agentcore invoke` ile yap
    - `agentcore status` ve `agentcore logs runtime --tail` ile runtime'ın hazır olduğunu doğrula
    - Geçerli bir Cognito token'ı ile (`agentcore invoke --help` ile JWT/bearer token seçeneğini doğrula) `agentcore invoke --runtime agent --session-id <en az 33 karakterli kimlik> --payload '{"prompt":"Merhaba"}'` çağır; yanıtın Placeholder_Response veya (izin tablosu boşken) "Bu işlem için yetkiniz yok" olduğunu doğrula
    - Token olmadan veya süresi dolmuş token ile çağrının JWT_Authorizer tarafından Agent_Backend kodu çalışmadan reddedildiğini doğrula
    - `agentcore traces runtime list --since 15m` ile iz görünürlüğünü kontrol et
    - Sonuçları not et; sorunlar için README sorun giderme tablosuna ekleme öner
    - _Requirements: 13.2, 13.4, 13.6, 14.8, 14.9_

- [x] 14. README belgesini yaz
  - [x] 14.1 `Logistic_AI/README.md` dosyasını Türkçe yaz
    - Bölümler: proje amacı; mimari ve dağıtım topolojisi; klasör yapısı; ön koşullar (Node.js 20.12+, Python 3.12+, uv, AWS CDK, AgentCore_CLI 1.0.3, Bedrock ve AgentCore erişimli AWS kimlik bilgileri); Cognito kurulumu (kullanıcı havuzu, `USER_PASSWORD_AUTH` App Client, `SUPPLIER`/`MATERIAL_RESPONSIBLE`/`TRANSPORT_OFFICE` grupları, `customJWTAuthorizer` değerlerinin doldurulması); ortam değişkenleri (yalnızca adlar, gerçek değer yok); yerel çalıştırma (`agentcore dev --port 8081`, `agentcore invoke --runtime agent --local --port 8081 --payload '{"prompt":"..."}'`, Streamlit_Client komutu, 8080'in kullanılmaması); dağıtım (`agentcore deploy`, ilk dağıtım yaklaşık 5-8 dakika); dağıtılmış ajanı çağırma (`agentcore invoke --runtime agent --session-id <kimlik> --payload '{"prompt":"..."}'`, oturum kimliği en az 33 karakter); durum/günlük/izleme (`agentcore status`, `agentcore logs runtime --tail`, `agentcore traces runtime list --since 15m`); sorun giderme tablosu (30 sn başlatma aşımı, 33 karakterden kısa oturum kimliği, inference profile öneki olmayan model kimliği, ARM64 wheel bulunamaması, izin reddedildi, 8081 kullanımda); güvenlik notları (sırlar kaynak kodda ve sürüm kontrolünde yok, IAM rolleri elle düzenlenmez, yetkilendirme Agent_Backend'de zorunlu); gelecek kapsam (Bedrock model çağrıları, Tools, Memory, Skills, MCP)
    - Bellek desteğinin (`agentMemory`) Faz 1'de kaldırıldığını ve gelecek kapsam olduğunu belirt
    - _Requirements: 12.5, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 14.9, 14.10, 14.11, 14.12_

  - [ ]* 14.2 README içerik kontrolü için doküman testi yaz
    - Gerekli bölüm başlıklarının, zorunlu komutların (`agentcore dev --port 8081`, `agentcore deploy`, `agentcore status`, `agentcore logs runtime --tail`, `agentcore traces runtime list --since 15m`), sorun giderme tablosundaki altı hatanın ve 8080 uyarısının bulunduğunu; gerçek değer, şifre veya token içermediğini doğrula
    - Dosya: `app/agent/tests/test_readme_content.py`
    - _Requirements: 14.1, 14.2, 14.5, 14.6, 14.9, 14.10_

- [~] 15. Final checkpoint - Tüm testlerin geçtiğinden emin ol
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` ile işaretli görevler isteğe bağlıdır ve daha hızlı bir MVP için atlanabilir.
- Her görev, izlenebilirlik için ilgili gereksinimlere başvurur.
- Kontrol noktaları artımlı doğrulama sağlar.
- Özellik testleri Hypothesis ile yazılır, en az 100 iterasyon çalışır ve `Feature: logistics-ai-auth, Property {numara}: {özellik metni}` etiketini taşır. Özellikler 1-25 tasarımdaki numaralarla eşleşir.
- Shared_Auth_Package ve Agent_Backend testleri `Logistic_AI/app/agent/tests/`, Streamlit_Client testleri `Logistic_AI/streamlit_client/tests/` altındadır.
- Her rol için somut izin listeleri henüz belirlenmemiştir (design.md Açık Soru 1). Faz 1'de varsayılan izin tablosu boştur ve deny-by-default nedeniyle tüm korumalı işlemler (Agent_Backend'in `chat:invoke` izni dahil) reddedilir; Placeholder_Response yolunu uçtan uca görmek için `config/permissions.json` içinde en az bir role `chat:invoke` izni eklenmesi (yalnızca yapılandırma değişikliği) gerekebilir. Bu kararı kullanıcıyla netleştirin.
- Doğrulanmış JWT'nin Agent_Backend işleyicisine ulaşma yöntemi (design.md Açık Soru 2) görev 6.4'te CLI 1.0.3 ve `bedrock-agentcore` SDK sürümüne karşı doğrulanmalıdır.
- Gerçek Cognito havuzuna karşı entegrasyon testleri, TLS 1.2+ doğrulaması, gizli bilgi taraması (`detect-secrets`/`gitleaks`) ve performans hedefleri (2 sn, 200 ms) otomatik kodlama görevi olarak kapsanmamıştır; ortam düzeyinde ayrıca doğrulanmalıdır.
- Görev 13.1 (`agentcore deploy`) kullanıcı onayı gerektirir; onay verilmezse sonraki dağıtım sonrası görev (13.2) atlanır.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "3.1", "4.3", "6.1", "6.2", "8.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "2.5", "3.2", "3.3", "4.1", "4.7", "4.8", "6.3", "6.5", "6.6", "8.2", "8.3", "8.4"] },
    { "id": 4, "tasks": ["3.4", "4.2", "4.4", "4.5", "6.7", "9.3"] },
    { "id": 5, "tasks": ["3.5", "3.6", "3.7", "3.8", "4.6", "4.9", "4.10", "4.11", "6.4", "9.1", "9.9"] },
    { "id": 6, "tasks": ["6.8", "6.9", "6.10", "7.1", "9.2", "9.5", "9.6", "9.7"] },
    { "id": 7, "tasks": ["9.4", "9.8", "10.1", "10.2", "10.3"] },
    { "id": 8, "tasks": ["10.4", "10.5"] },
    { "id": 9, "tasks": ["12.1", "14.1"] },
    { "id": 10, "tasks": ["13.1", "14.2"] },
    { "id": 11, "tasks": ["13.2"] }
  ]
}
```
