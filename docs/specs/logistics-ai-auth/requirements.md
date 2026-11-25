# Requirements Document

## Introduction

Logistics AI Assistant, tedarikçilerin, malzeme sorumlularının ve transport ofisi çalışanlarının lojistik süreçlerini yapay zekâ üzerinden yönetmesini hedefleyen kurumsal bir chatbot uygulamasıdır. Proje `Logistic_AI` klasörü altında oluşturulacaktır.

Bu doküman yalnızca Faz 1'i kapsar: Kullanıcı Kimlik Doğrulama ve Yetkilendirme. Uygulama Python ile geliştirilecek, kimlik doğrulama Amazon Cognito ile yapılacaktır. Mimari modüler ve genişletilebilir olacaktır.

### Dağıtım Mimarisi Notu

Streamlit arayüzü (giriş ekranı ve chatbot ana ekranı) Amazon Bedrock AgentCore Runtime üzerinde çalıştırılamaz. Bu nedenle uygulama iki parçadan oluşur:

- Streamlit_Client: Kullanıcıyı Amazon Cognito ile doğrular ve kullanıcının Cognito token'ı ile AgentCore_Runtime'daki ajanı HTTPS üzerinden çağırır. Barındırma hedefi (yerel çalıştırma veya konteyner) bir dağıtım seçeneğidir ve zorunlu kılınmaz.
- Agent_Backend: Strands Agents tabanlı ajan iskeleti olup AgentCore CLI (`@aws/agentcore` 1.0.3) ile `agentcore create --name LogisticAI --template agent-python-strands` komutuyla `Logistic_AI` klasörü altında oluşturulur ve `agentcore deploy` ile AgentCore_Runtime'a dağıtılır. AgentCore_Runtime, Cognito JWT inbound authorizer ile yapılandırılır. Agent_Backend, rolü gönderilen token'dan bağımsız olarak türetir ve rol bazlı yetkilendirmeyi kendisi uygular.

Auth_Service ve Authorization_Service mantığı, hem Streamlit_Client'ın hem de Agent_Backend'in kullandığı ortak bir Python paketi olarak sunulur.

### Kapsam Dışı (Gelecek Kapsam)

Aşağıdaki öğeler Faz 1'de geliştirilmeyecektir. Yalnızca ilerleyen aşamalar için not edilmiştir:

- Amazon Bedrock model çağrıları
- Gerçek ajan davranışı (model tabanlı akıl yürütme)
- Skills
- Tools (yalnızca boş `tools` paketi bulunur)
- Memory (AgentCore Memory kaynakları Faz 1'de oluşturulmaz veya etkinleştirilmez)
- MCP entegrasyonları

Faz 1'de Agent_Backend yalnızca Strands ajan iskeleti olarak bulunur ve Amazon Bedrock modellerini çağırmadan deterministik bir yer tutucu yanıt döndürür. Chatbot ana ekranı bu entegrasyonlar olmadan, yalnızca ekran iskeleti ve yer tutucu yanıtla sunulur.

## Glossary

- **Logistics_AI_App**: Streamlit ile geliştirilen, Logistic_AI klasöründeki web uygulaması.
- **Login_Screen**: Kullanıcının kullanıcı adı ve şifre girdiği giriş ekranı.
- **Chatbot_Home_Screen**: Başarılı girişten sonra açılan chatbot ana ekranı.
- **Auth_Service**: Amazon Cognito ile iletişim kuran kimlik doğrulama modülü.
- **Cognito_User_Pool**: Kullanıcı hesaplarını ve rol gruplarını tutan Amazon Cognito kullanıcı havuzu.
- **Authorization_Service**: Rol bazlı yetkilendirme kararlarını backend tarafında veren modül.
- **Session_Manager**: Oturum durumunu, token'ları ve oturum süresini yöneten modül.
- **Role**: Kullanıcının yetki düzeyi. Geçerli değerler `SUPPLIER`, `MATERIAL_RESPONSIBLE` ve `TRANSPORT_OFFICE`'tir.
- **SUPPLIER**: Tedarikçi kullanıcıların rolü.
- **MATERIAL_RESPONSIBLE**: Malzeme sorumlusu kullanıcıların rolü.
- **TRANSPORT_OFFICE**: Transport ofisi çalışanlarının rolü.
- **Permission**: Bir rolün erişebileceği veri veya fonksiyon için tanımlı izin.
- **ID_Token**: Cognito'nun giriş sonrası ürettiği, kullanıcı kimliğini ve grup bilgisini taşıyan JWT.
- **Secret_Store**: Şifre, API anahtarı ve yapılandırma değerlerinin tutulduğu ortam değişkeni veya yönetilen sır deposu.
- **AgentCore_Runtime**: Agent_Backend'i barındıran Amazon Bedrock AgentCore yönetilen çalışma ortamı. Çalışma zamanı adı `agent`'tır.
- **Agent_Backend**: `Logistic_AI/app/agent` altında bulunan, Strands Agents SDK ile yazılmış ve AgentCore_Runtime üzerinde çalışan ajan uygulaması.
- **Streamlit_Client**: Giriş ekranını ve chatbot ana ekranını sunan, AgentCore_Runtime üzerinde çalışmayan ayrı Streamlit uygulaması.
- **AgentCore_CLI**: `@aws/agentcore` npm paketi sürüm 1.0.3 ile gelen `agentcore` komut satırı aracı.
- **Shared_Auth_Package**: Auth_Service ve Authorization_Service mantığını içeren, Streamlit_Client ve Agent_Backend tarafından ortak kullanılan Python paketi.
- **JWT_Authorizer**: AgentCore_Runtime'ın `customJWTAuthorizer` ayarıyla Cognito_User_Pool discovery URL'si ve izin verilen App Client üzerinden gelen token'ları doğrulayan inbound kimlik doğrulama yapılandırması.
- **Placeholder_Response**: Agent_Backend'in Amazon Bedrock modelini çağırmadan döndürdüğü deterministik sabit yanıt.

## Requirements

### Requirement 1: Giriş Ekranı

**User Story:** Bir kullanıcı olarak, modern ve profesyonel bir giriş ekranı görmek istiyorum, böylece uygulamaya kolayca ve güvenle giriş yapabilirim.

#### Acceptance Criteria

1. WHEN kimliği doğrulanmamış bir kullanıcı Logistics_AI_App'i açtığında, THE Logistics_AI_App SHALL Login_Screen'i 2 saniye içinde göstermek ve Login_Screen dışındaki hiçbir uygulama ekranını göstermemek.
2. THE Login_Screen SHALL tam olarak üç etkileşimli öğe içermek: bir kullanıcı adı alanı, bir maskelenmiş şifre alanı (girilen her karakter nokta veya yıldız olarak görüntülenir) ve bir giriş butonu.
3. THE Login_Screen SHALL kullanıcı adı alanında en fazla 64 karakter ve şifre alanında en fazla 128 karakter girişine izin vermek.
4. THE Login_Screen SHALL uygulama adını "Logistics AI Assistant" metniyle, ekranın üst bölümünde, giriş alanlarından önce görünür şekilde göstermek.
5. IF kullanıcı kullanıcı adı alanını, şifre alanını veya her ikisini boş (veya yalnızca boşluk karakterlerinden oluşan) bırakıp giriş butonuna basarsa, THEN THE Login_Screen SHALL kimlik doğrulama isteği göndermemek ve hangi alanın (kullanıcı adı, şifre veya her ikisi) eksik olduğunu belirten bir hata mesajı göstermek.
6. IF kimlik doğrulama isteği başarısız olursa veya 30 saniye içinde yanıt alınamazsa, THEN THE Login_Screen SHALL yükleniyor göstergesini kaldırmak, giriş butonunu yeniden etkinleştirmek, girişin başarısız olduğunu belirten bir hata mesajı göstermek ve kullanıcı adı alanındaki değeri korurken şifre alanını temizlemek.
7. WHILE kimlik doğrulama isteği sürerken, THE Login_Screen SHALL giriş butonunu devre dışı bırakmak, butona basıldığı andan itibaren 200 milisaniye içinde bir yükleniyor göstergesi sunmak ve ikinci bir kimlik doğrulama isteği gönderilmesini engellemek.

### Requirement 2: Amazon Cognito ile Kimlik Doğrulama

**User Story:** Bir kullanıcı olarak, kullanıcı adı ve şifremle giriş yapmak istiyorum, böylece kurumsal hesabımla doğrulanabilirim.

#### Acceptance Criteria

1. WHEN kullanıcı 1 ila 64 karakter uzunluğunda boş olmayan bir kullanıcı adı ve 1 ila 128 karakter uzunluğunda boş olmayan bir şifre gönderdiğinde, THE Auth_Service SHALL kimlik bilgilerini Cognito_User_Pool'a karşı doğrulamak ve sonucu 5 saniye içinde kullanıcıya bildirmek.
2. WHEN Cognito_User_Pool kimlik doğrulamasını başarıyla tamamladığında, THE Auth_Service SHALL ID_Token, access token ve refresh token'ı Session_Manager'a iletmek ve kullanıcıya giriş başarılı yanıtı döndürmek.
3. IF kullanıcı adı veya şifre boşsa ya da belirtilen uzunluk sınırlarının dışındaysa, THEN THE Auth_Service SHALL isteği Cognito_User_Pool'a göndermeden reddetmek ve hangi alanın geçersiz olduğunu belirten bir doğrulama hatası döndürmek.
4. IF kullanıcı adı veya şifre hatalıysa, THEN THE Auth_Service SHALL kullanıcı adının mı şifrenin mi hatalı olduğunu belirtmeyen genel bir "Geçersiz kullanıcı adı veya şifre" hatası döndürmek ve Session_Manager'a hiçbir token iletmemek.
5. IF Cognito_User_Pool'a erişilemiyorsa veya 5 saniye içinde yanıt vermezse, THEN THE Auth_Service SHALL kullanıcıya genel bir hizmet hatası mesajı döndürmek, teknik ayrıntıyı günlüğe yazmak ve kullanıcıya teknik ayrıntı göstermemek.
6. IF Cognito kullanıcı için yeni şifre belirleme (NEW_PASSWORD_REQUIRED) zorluğu döndürürse, THEN THE Auth_Service SHALL kullanıcıya şifresini değiştirmesi gerektiğini bildirmek ve Session_Manager'a hiçbir token iletmemek.
7. IF aynı kullanıcı adıyla art arda 5 başarısız giriş denemesi yapılırsa, THEN THE Auth_Service SHALL Cognito'nun geçici kilitleme yanıtını kullanıcıya genel bir "Çok fazla deneme, lütfen daha sonra tekrar deneyin" mesajıyla iletmek ve kilitleme süresi dolana kadar bu kullanıcı adı için yapılan girişleri Cognito_User_Pool'a göndermeden reddetmek.

### Requirement 3: Rol Tanımları ve Rolün Belirlenmesi

**User Story:** Bir sistem yöneticisi olarak, kullanıcıların rollerinin giriş sonrasında güvenli şekilde belirlenmesini istiyorum, böylece yetkiler istemci tarafından değiştirilemesin.

#### Acceptance Criteria

1. THE Authorization_Service SHALL yalnızca `SUPPLIER`, `MATERIAL_RESPONSIBLE` ve `TRANSPORT_OFFICE` değerlerini geçerli Role olarak kabul etmek ve bu üç değer dışındaki her değeri (büyük/küçük harf farkı dahil, örneğin `supplier`) geçersiz saymak.
2. WHEN kimlik doğrulama başarılı olduğunda, THE Authorization_Service SHALL kullanıcının Role değerini, ID_Token doğrulaması başarıyla tamamlandıktan sonra, ID_Token içindeki `cognito:groups` talebinde yer alan geçerli grup adından türetmek.
3. WHEN bir ID_Token alındığında, THE Authorization_Service SHALL Role türetmeden önce ID_Token'ın imzasını, bitiş süresini (`exp` değeri geçmişte olmamalıdır), issuer değerini ve audience değerini doğrulamak.
4. IF ID_Token doğrulaması başarısız olursa (imza geçersiz, süre dolmuş, issuer veya audience eşleşmiyor ya da token eksik/okunamıyor), THEN THE Authorization_Service SHALL oturumu reddetmek, hiçbir Role değeri atamamak ve kullanıcıyı 2 saniye içinde Login_Screen'e yönlendirmek.
5. IF `cognito:groups` talebi yoksa, boşsa veya geçerli rollerden hiçbirini içermiyorsa, THEN THE Authorization_Service SHALL girişi reddetmek, hiçbir oturum oluşturmamak ve "Hesabınıza bir rol atanmamış" mesajını göstermek.
6. IF `cognito:groups` talebi birden fazla farklı geçerli Role değeri içeriyorsa, THEN THE Authorization_Service SHALL girişi reddetmek, hiçbir oturum oluşturmamak ve kullanıcıya yöneticiyle iletişime geçmesini belirten bir mesaj göstermek.
7. THE Authorization_Service SHALL Role değerini yalnızca doğrulanmış ID_Token'dan okumak ve istek parametrelerinden, istek gövdesinden (AgentCore payload dahil), çerezlerden, yerel depolamadan veya istemci tarafından değiştirilebilir başka bir alandan okumamak.
8. IF `cognito:groups` talebi geçerli bir Role değerinin yanı sıra geçersiz grup adları içeriyorsa ve yalnızca bir geçerli Role değeri bulunuyorsa, THEN THE Authorization_Service SHALL geçersiz grup adlarını yok saymak ve tek geçerli Role değerini kullanıcının Role değeri olarak atamak.

### Requirement 4: Rol Bazlı Yetkilendirme

**User Story:** Bir kurumsal kullanıcı olarak, yalnızca yetkili olduğum veri ve fonksiyonlara erişmek istiyorum, böylece diğer rollerin verileri korunur.

#### Acceptance Criteria

1. THE Authorization_Service SHALL her Role için erişilebilecek Permission kümesini tek bir merkezi izin tablosunda tanımlamak ve bu tablonun içeriğinin kod değişikliği ve yeniden derleme gerektirmeden yapılandırma yoluyla değiştirilebilmesini sağlamak.
2. WHEN bir kullanıcı korumalı bir fonksiyonu veya veriyi istediğinde, THE Authorization_Service SHALL isteği işlemeden önce kullanıcının Role değerine karşılık gelen Permission kümesini backend tarafında kontrol etmek ve yetki kararını isteğin alınmasından itibaren 200 ms içinde vermek.
3. IF kullanıcının Role değeri istenen Permission'ı içermiyorsa, THEN THE Authorization_Service SHALL isteği işlemeden reddetmek, çağırana "Bu işlem için yetkiniz yok" hata mesajını döndürmek ve isteğin istenen veri veya fonksiyon üzerinde hiçbir değişiklik veya veri ifşası oluşturmadığını garanti etmek.
4. IF bir Permission izin tablosunda tanımlı değilse veya kullanıcının Role değeri boş ya da izin tablosunda tanımlı değilse, THEN THE Authorization_Service SHALL isteği varsayılan olarak reddetmek ve çağırana yetkisiz erişimi belirten bir hata döndürmek.
5. WHEN bir yetkilendirme isteği reddedildiğinde, THE Authorization_Service SHALL kullanıcı adını, Role değerini, istenen Permission'ı ve zaman damgasını (UTC, saniye hassasiyetinde) içeren bir denetim kaydı yazmak.
6. IF denetim kaydı yazılamazsa, THEN THE Authorization_Service SHALL isteğin reddedilmiş durumunu korumak ve çağırana reddedilme sonucunu döndürmeye devam etmek.
7. THE Authorization_Service SHALL yetki kontrolünü, kullanıcı arayüzünde öğelerin gizlenmesine veya gösterilmesine bağlı olmaksızın, Agent_Backend katmanında her korumalı istek için uygulamak; Streamlit_Client tarafındaki kontroller yalnızca ek kullanıcı deneyimi katmanı olarak kabul edilmek ve Agent_Backend kontrolünün yerine geçmemek.
8. FOR ALL Role ve Permission çiftleri, THE Authorization_Service SHALL izin tablosu değişmediği sürece aynı girdi için aynı izin kararını (izin ver veya reddet) döndürmek (deterministik karar özelliği).

### Requirement 5: Chatbot Ana Ekranı

**User Story:** Bir kullanıcı olarak, giriş yaptıktan sonra chatbot ana ekranını görmek ve kim olarak giriş yaptığımı bilmek istiyorum, böylece doğru hesapla çalıştığımdan emin olabilirim.

#### Acceptance Criteria

1. WHEN kimlik doğrulama ve rol belirleme başarıyla tamamlandığında, THE Logistics_AI_App SHALL Chatbot_Home_Screen'i 2 saniye içinde açmak.
2. WHEN Chatbot_Home_Screen açıldığında, THE Chatbot_Home_Screen SHALL oturum açmış kullanıcının kullanıcı adını ekranın üst bölümünde, kısaltmadan ve en fazla 64 karaktere kadar tam olarak göstermek.
3. WHEN Chatbot_Home_Screen açıldığında, THE Chatbot_Home_Screen SHALL oturum açmış kullanıcının Role değerini kullanıcı adının yanında göstermek.
4. WHEN Chatbot_Home_Screen açıldığında, THE Chatbot_Home_Screen SHALL tam olarak bir mesaj giriş alanı ve tam olarak bir sohbet geçmişi alanı içeren chatbot ekran iskeletini göstermek; sohbet geçmişi alanı ilk açılışta boş olmak.
5. WHERE yapay zekâ entegrasyonu etkinleştirilmemişse, THE Chatbot_Home_Screen SHALL Chatbot_Home_Screen açık olduğu sürece görünür kalan, yapay zekâ yanıtlarının henüz kullanılamadığını belirten bir bilgi mesajı göstermek.
6. IF kimliği doğrulanmamış bir kullanıcı Chatbot_Home_Screen'e doğrudan erişmeye çalışırsa, THEN THE Logistics_AI_App SHALL Chatbot_Home_Screen içeriğini göstermeden kullanıcıyı Login_Screen'e yönlendirmek.
7. IF kimlik doğrulama başarılı olduğu halde Role değeri belirlenemezse, THEN THE Logistics_AI_App SHALL Chatbot_Home_Screen'i açmamak ve kullanıcıyı rolün belirlenemediğini belirten bir hata mesajıyla Login_Screen'e yönlendirmek.

### Requirement 6: Güvenli Oturum Yönetimi

**User Story:** Bir kullanıcı olarak, oturumumun güvenli yönetilmesini istiyorum, böylece hesabım yetkisiz kullanıma karşı korunur.

#### Acceptance Criteria

1. WHEN giriş başarılı olduğunda, THE Session_Manager SHALL access token'ı, refresh token'ı ve kullanıcı bilgilerini yalnızca sunucu tarafı Streamlit oturum durumunda saklamak.
2. THE Session_Manager SHALL token'ları ve şifreyi tarayıcı çerezinde, URL parametresinde, günlük çıktısında veya istemciye gönderilen herhangi bir yanıtta saklamamak veya yazmamak.
3. WHEN access token'ın bitiş süresine 5 dakika veya daha az kaldığında, THE Session_Manager SHALL refresh token ile token'ları yenilemeyi en fazla 1 kez denemek ve başarılı yenilemeden sonra oturum durumundaki token'ları yeni değerlerle değiştirmek.
4. IF token yenileme başarısız olursa veya 10 saniye içinde yanıt alınamazsa, THEN THE Session_Manager SHALL oturum durumundaki tüm token'ları ve kullanıcı bilgilerini silmek, oturumu sonlandırmak, kullanıcıyı Login_Screen'e yönlendirmek ve oturumun sona erdiğini belirten bir hata mesajı göstermek.
5. WHEN korumalı bir istek alındığında, THE Session_Manager SHALL isteği işlemeden önce oturumun geçerliliğini (access token'ın süresinin dolmamış olması ve oturum durumunda bulunması) kontrol etmek.
6. IF oturum geçerlilik kontrolü başarısız olursa, THEN THE Session_Manager SHALL korumalı isteği işlememek, oturumu sonlandırmak ve kullanıcıyı Login_Screen'e yönlendirmek.
7. WHEN kullanıcı yapılandırılmış boşta kalma süresi boyunca (varsayılan 30 dakika) etkileşimde bulunmadığında, THE Session_Manager SHALL oturum durumundaki tüm token'ları ve kullanıcı bilgilerini silmek, oturumu sonlandırmak ve kullanıcıyı Login_Screen'e yönlendirmek.
8. THE Session_Manager SHALL boşta kalma süresini yapılandırma ile 1 ile 480 dakika arasında değiştirilebilir bir değer olarak sunmak ve değer belirtilmediğinde 30 dakika kullanmak.
9. IF yapılandırılmış boşta kalma süresi 1 ile 480 dakika aralığının dışındaysa veya sayısal değilse, THEN THE Session_Manager SHALL yapılandırma değerini reddetmek ve 30 dakikalık varsayılan değeri kullanmak.

### Requirement 7: Çıkış (Logout)

**User Story:** Bir kullanıcı olarak, oturumumu kapatabilmek istiyorum, böylece paylaşılan cihazlarda hesabım korunur.

#### Acceptance Criteria

1. WHILE kullanıcı kimlik doğrulanmış durumdayken, THE Chatbot_Home_Screen SHALL ekranın görünür alanında, sayfa kaydırılmadan erişilebilen bir çıkış butonu göstermek.
2. WHEN kullanıcı çıkış butonuna bastığında, THE Session_Manager SHALL oturum durumundaki access token, ID token ve refresh token değerlerini, kullanıcı adını ve Role değerini 1 saniye içinde silmek.
3. WHEN kullanıcı çıkış butonuna bastığında, THE Auth_Service SHALL kullanıcının Cognito refresh token'ının iptal edilmesi için Cognito'ya bir istek göndermek.
4. WHEN yerel oturum verisi silindiğinde ve Cognito token iptal isteği tamamlandığında veya başarısız olduğunda, THE Logistics_AI_App SHALL kullanıcıyı 2 saniye içinde Login_Screen'e yönlendirmek.
5. IF Cognito token iptali başarısız olursa veya 10 saniye içinde yanıt alınamazsa, THEN THE Session_Manager SHALL yerel oturum verisini yine de silmek, hatayı günlüğe yazmak ve kullanıcıyı Login_Screen'e yönlendirmek.
6. WHEN çıkış yapıldıktan sonra tarayıcıda geri düğmesi kullanıldığında, THE Logistics_AI_App SHALL Login_Screen'i göstermek ve önceki oturuma ait hiçbir kullanıcı adını, Role değerini veya sohbet içeriğini göstermemek.
7. IF çıkış yapıldıktan sonra silinmiş token'larla korumalı bir ekrana erişim denenirse, THEN THE Logistics_AI_App SHALL erişimi reddetmek ve kullanıcıyı Login_Screen'e yönlendirmek.

### Requirement 8: Sır ve Yapılandırma Yönetimi

**User Story:** Bir geliştirici olarak, şifrelerin ve API anahtarlarının kaynak kodda tutulmamasını istiyorum, böylece gizli bilgiler sızmaz.

#### Acceptance Criteria

1. WHEN Logistics_AI_App başlatılır, THE Logistics_AI_App SHALL Cognito User Pool ID, App Client ID, bölge ve diğer hassas yapılandırma değerlerinin tamamını yalnızca Secret_Store'dan okumak ve bu değerleri kaynak koddaki sabitlerden veya sürüm kontrolüne eklenen dosyalardan okumamak.
2. THE Logistics_AI_App SHALL kaynak kodunda, test verisinde ve sürüm kontrolüne eklenen dosyalarda (geçmiş commit'ler dahil) gerçek bir şifre, API anahtarı veya token değeri içermemek; otomatik bir gizli bilgi taraması bu dosyalarda sıfır bulgu raporlamalıdır.
3. THE Logistics_AI_App SHALL yerel geliştirme için kullanılan sır dosyalarını (ör. `.env.local`) sürüm kontrolü dışında bırakan bir `.gitignore` kuralı içermek; bu dosyalar `git status` çıktısında izlenmeyen (untracked) dosya olarak listelenmemelidir.
4. IF zorunlu bir yapılandırma değeri Secret_Store'da bulunamazsa veya boş bir değer içeriyorsa, THEN THE Logistics_AI_App SHALL başlangıçta eksik değerin adını (değerin kendisini değil) belirten bir yapılandırma hatası vermek, sıfır olmayan bir çıkış durumuyla sonlanmak ve hiçbir isteği kabul etmemek.
5. IF Secret_Store başlangıçta 10 saniye içinde yanıt vermezse veya erişim hatası dönerse, THEN THE Logistics_AI_App SHALL hatanın kaynağını (Secret_Store erişimi) belirten bir yapılandırma hatası vermek ve uygulamayı başlatmamak.
6. THE Logistics_AI_App SHALL kullanıcı şifrelerini, token'ları ve API anahtarlarını günlük kayıtlarına (log) hiçbir günlük seviyesinde yazmamak.
7. THE Logistics_AI_App SHALL Cognito ile tüm iletişimde yalnızca TLS 1.2 veya üzeri ile korunan bağlantılar kullanmak.
8. IF Cognito ile TLS korumalı olmayan bir bağlantı kurulması denenirse, THEN THE Logistics_AI_App SHALL bağlantıyı reddetmek ve hiçbir veri göndermeden bağlantı hatası bildirmek.

### Requirement 9: Modüler ve Genişletilebilir Mimari

**User Story:** Bir geliştirici olarak, kodun modüler ve genişletilebilir olmasını istiyorum, böylece ilerleyen fazlarda Bedrock, Agent, Skills, Tools, Memory ve MCP kolayca eklenebilir.

#### Acceptance Criteria

1. THE Logistics_AI_App SHALL kullanıcı arayüzü, kimlik doğrulama, yetkilendirme, oturum yönetimi ve yapılandırma sorumluluklarını her biri ayrı bir modülde olacak şekilde (toplam 5 ayrı modül) uygulamak ve hiçbir modülün başka bir modülün iç (private) uygulama detaylarına doğrudan erişmemesini sağlamak.
2. THE Logistics_AI_App SHALL Auth_Service'i bir soyutlama arayüzü arkasında sunmak, böylece Cognito istemcisi test sırasında Cognito'ya ağ çağrısı yapmayan bir sahte (mock) uygulama ile, Auth_Service arayüzünü kullanan hiçbir modülün kodu değiştirilmeden değiştirilebilsin.
3. WHEN yeni bir Role veya Permission tanımı izin tablosuna eklenir, THE Authorization_Service SHALL yeni tanımı Authorization_Service modül kodunda hiçbir satırı değiştirmeden değerlendirmek ve ilgili izin kontrolünü yeni tanıma göre sonuçlandırmak.
4. IF izin tablosuna eklenen bir Role veya Permission tanımı geçersizse (boş ad, 64 karakterden uzun ad veya mevcut bir tanımla aynı ad), THEN THE Authorization_Service SHALL tanımı reddetmek, reddetme nedenini belirten bir hata döndürmek ve mevcut izin tablosunu değiştirmeden korumak.
5. WHEN kullanıcı kimlik doğrulamasını başarıyla tamamlar, THE Logistics_AI_App SHALL kimliği doğrulanmış kullanıcı bağlamını (kullanıcı adı ve Role) tek bir arayüz üzerinden gelecekteki yapay zekâ bileşenlerine sunmak.
6. IF kimliği doğrulanmış bir kullanıcı oturumu yoksa veya oturum sona ermişse, THEN THE Logistics_AI_App SHALL kullanıcı bağlamı arayüzünden kullanıcı adı ve Role değeri döndürmemek ve çağırana kimliğin doğrulanmadığını belirten bir hata döndürmek.
7. THE Logistics_AI_App SHALL Faz 1 kapsamında Amazon Bedrock model çağrısı, Skills, Tools uygulaması, Memory kaynağı veya MCP bileşeni içermemek; Requirement 12'de tanımlanan Strands ajan iskeleti bu kısıttan hariçtir.
8. THE Logistics_AI_App SHALL Auth_Service ve Authorization_Service mantığını Shared_Auth_Package olarak sunmak ve Streamlit_Client ile Agent_Backend'in aynı paket kodunu içe aktararak kullanmasını sağlamak.
9. THE Shared_Auth_Package SHALL yalnızca AgentCore_Runtime ARM64 ortamında kurulabilen bağımlılıklara (ARM64 Linux için hazır wheel sunan paketlere) sahip olmak.

### Requirement 10: Denetim Günlüğü ve Hata Yönetimi

**User Story:** Bir güvenlik yöneticisi olarak, kimlik doğrulama olaylarının kaydedilmesini istiyorum, böylece olaylar izlenebilir ve denetlenebilir.

#### Acceptance Criteria

1. WHEN bir giriş denemesi tamamlandığında, THE Logistics_AI_App SHALL kullanıcı adını (en fazla 255 karakter), sonucu (başarılı veya başarısız) ve UTC cinsinden zaman damgasını (saniye hassasiyetinde veya daha ince) içeren bir denetim kaydı yazmak.
2. WHEN bir kullanıcı çıkış yaptığında, THE Logistics_AI_App SHALL kullanıcı adını ve UTC cinsinden zaman damgasını (saniye hassasiyetinde veya daha ince) içeren bir denetim kaydı yazmak.
3. WHEN bir oturum zaman aşımı nedeniyle sonlandığında, THE Logistics_AI_App SHALL kullanıcı adını, neden bilgisini (zaman aşımı olduğunu belirten değer) ve UTC cinsinden zaman damgasını (saniye hassasiyetinde veya daha ince) içeren bir denetim kaydı yazmak.
4. IF beklenmeyen bir hata oluşursa, THEN THE Logistics_AI_App SHALL kullanıcıya yığın izi, dosya yolu, sorgu veya dahili bileşen adı içermeyen, işlemin tamamlanamadığını belirten genel bir hata mesajı göstermek ve hata ayrıntısını zaman damgasıyla birlikte günlüğe yazmak.
5. IF bir denetim kaydı yazılamazsa, THEN THE Logistics_AI_App SHALL ilgili kimlik doğrulama işleminin sonucunu değiştirmeden sürdürmek, kullanıcıya genel bir hata mesajı göstermeden başarısızlığı günlüğe yazmayı en fazla 3 kez denemek ve tüm denemeler başarısız olursa başarısızlığı hata günlüğüne kaydetmek.
6. THE Logistics_AI_App SHALL denetim kayıtlarında parola, oturum belirteci ve diğer kimlik doğrulama sırlarını hiçbir koşulda saklamamak.

### Requirement 11: AgentCore CLI Proje İskeleti

**User Story:** Bir geliştirici olarak, proje iskeletinin AgentCore CLI Strands düzenine uymasını istiyorum, böylece uygulama standart araçlarla geliştirilebilir ve dağıtılabilir.

#### Acceptance Criteria

1. THE Logistics_AI_App SHALL Agent_Backend iskeletini `Logistic_AI` klasörü altında, AgentCore_CLI 1.0.3 ile `agentcore create --name LogisticAI --template agent-python-strands` komutu çalıştırılarak oluşturmak ve proje dizinini elle oluşturmamak.
2. THE Agent_Backend SHALL şu dosya ve klasörleri içermek: `agentcore/agentcore.json`, `app/agent/main.py`, `app/agent/parse.py`, `app/agent/model/load.py`, `app/agent/memory/session.py`, `app/agent/pyproject.toml` ve `app/agent/tests/`.
3. THE `agentcore/agentcore.json` dosyası SHALL adı `agent` olan tam olarak bir runtime tanımı içermek.
4. THE Agent_Backend SHALL Python 3.12 veya üzeri sürümde çalışmak ve tüm fonksiyon imzalarında tür ipuçları (type hints) kullanmak.
5. THE `app/agent/pyproject.toml` dosyası SHALL yalnızca çalışma zamanı paketlerini `[project].dependencies` altında listelemek ve `pytest` ile diğer test araçlarını `[dependency-groups]` altındaki `dev` grubunda tanımlamak.
6. THE Agent_Backend SHALL yalnızca AgentCore_Runtime ARM64 (Graviton) ortamında kurulabilen, ARM64 Linux için hazır wheel sunan çalışma zamanı bağımlılıklarını kullanmak.
7. THE Agent_Backend SHALL `BedrockAgentCoreApp` sınıfını `bedrock_agentcore.runtime` modülünden içe aktarmak ve `bedrock_agentcore` paket kökünden içe aktarmamak.
8. THE Agent_Backend SHALL Strands ajanını modül yüklenirken değil, ilk istekte (lazy initialization) oluşturmak, böylece çalışma zamanı başlatma süresi 30 saniyelik sınırı aşmasın.
9. THE Agent_Backend SHALL giriş noktasını `@app.entrypoint` ile süslenmiş bir asenkron üreteç (async generator) fonksiyonu olarak tanımlamak ve `main.py` içindeki `__main__` bloğunda `app.run()` çağırmak.
10. THE `parse.py` modülü SHALL istek yükünden `prompt` ve `actorId` alanlarını okumak.
11. IF istek yükünde `prompt` alanı yoksa veya boşsa, THEN THE Agent_Backend SHALL modeli veya ajanı çalıştırmadan doğrulama hatası içeren bir yanıt döndürmek.
12. FOR ALL geçerli `prompt` ve `actorId` değer çiftleri, `parse.py` ayrıştırması SHALL aynı alan değerlerini döndürmek (yükü serileştirip yeniden ayrıştırma sonucu eşdeğer bir yük üretmeli; round-trip özelliği).

### Requirement 12: Strands Ajan İskeleti ve Yer Tutucu Yanıt

**User Story:** Bir geliştirici olarak, Faz 1'de model çağırmayan ancak ileride genişletilebilen bir Strands ajan iskeleti istiyorum, böylece Bedrock, Tools ve Memory sonraki fazlarda kolayca eklenir.

#### Acceptance Criteria

1. THE Agent_Backend SHALL AgentCore_Runtime'a `agent` adıyla kayıtlı bir Strands ajan iskeleti içermek.
2. WHEN geçerli ve yetkili bir istek alındığında, THE Agent_Backend SHALL Amazon Bedrock modelini çağırmadan Placeholder_Response döndürmek.
3. FOR ALL geçerli `prompt` değerleri, THE Agent_Backend SHALL aynı Placeholder_Response metnini döndürmek (deterministik yanıt).
4. THE Agent_Backend SHALL genişletme noktaları olarak `app/agent/model/load.py` (model yükleyici), `app/agent/tools/` (araç paketi), `app/agent/prompts/system_prompt.py` (sistem istemi modülü) ve `app/agent/memory/session.py` (bellek oturum modülü) dosyalarını, Faz 1'de işlevsiz (stub veya devre dışı) olarak içermek.
5. THE Agent_Backend SHALL Faz 1'de AgentCore Memory kaynağı oluşturmamak ve etkinleştirmemek; şablonun getirdiği `agentMemory` tanımı `agentcore/agentcore.json` içinden kaldırılmalı ve bellek desteği README'de gelecek kapsam olarak belgelenmelidir.
6. WHERE model yükleyici gelecekte etkinleştirilirse, THE `model/load.py` modülü SHALL model kimliğini inference profile biçiminde (ör. `global.` önekli) kullanmak ve model kimliğini kaynak koda sabit yazmak yerine dağıtım zamanında `aws bedrock list-foundation-models --by-provider Anthropic` çıktısındaki ACTIVE modellerden belirlemek.
7. THE Agent_Backend SHALL kullanıcı mesajlarını, token'ları ve şifreleri günlüğe yazmamak.
8. THE Agent_Backend SHALL Placeholder_Response, doğrulama hatası ve yetkisiz erişim yolları için pytest birim testlerine sahip olmak.

### Requirement 13: AgentCore Dağıtımı ve Cognito JWT ile Korunan Erişim

**User Story:** Bir güvenlik yöneticisi olarak, AgentCore Runtime'ın yalnızca geçerli Cognito token'larını kabul etmesini istiyorum, böylece yetkisiz istekler ajana ulaşmaz.

#### Acceptance Criteria

1. THE Logistics_AI_App SHALL Agent_Backend'i `agentcore deploy` komutuyla AgentCore_Runtime'a dağıtmak.
2. THE `agentcore/agentcore.json` dosyası SHALL `agent` runtime'ının `envVars` listesinde `UNIFIED_TRACES_DESTINATION_ENABLED` değişkenini `true` değeriyle içermek.
3. THE `agentcore/agentcore.json` dosyası SHALL `agent` runtime'ı için `customJWTAuthorizer` tanımı içermek; bu tanım Cognito_User_Pool discovery URL'sini ve izin verilen tek bir App Client kimliğini belirtmelidir.
4. WHEN AgentCore_Runtime geçerli bir Cognito token'ı olmadan veya geçersiz bir token ile çağrıldığında, THE JWT_Authorizer SHALL isteği Agent_Backend kodu çalışmadan reddetmek.
5. THE Streamlit_Client SHALL AgentCore_Runtime'ı yalnızca HTTPS üzerinden ve oturumdaki kullanıcının Cognito token'ını `Authorization: Bearer` başlığında göndererek çağırmak.
6. WHEN Streamlit_Client AgentCore_Runtime'ı çağırdığında, THE Streamlit_Client SHALL en az 33 karakter uzunluğunda bir runtime oturum kimliği kullanmak.
7. IF AgentCore_Runtime çağrısı 401 veya 403 yanıtı döndürürse, THEN THE Streamlit_Client SHALL Session_Manager üzerinden token yenilemeyi Requirement 6.3 kurallarıyla denemek ve yenileme başarısız olursa kullanıcıyı Login_Screen'e yönlendirmek.
8. IF AgentCore_Runtime çağrısı ağ hatası veya 30 saniye zaman aşımı nedeniyle başarısız olursa, THEN THE Streamlit_Client SHALL teknik ayrıntı içermeyen genel bir hata mesajı göstermek.
9. WHEN Agent_Backend bir istek aldığında, THE Agent_Backend SHALL Role değerini Requirement 3'teki kurallara göre, Streamlit_Client'tan bağımsız olarak, yalnızca doğrulanmış token'ın `cognito:groups` talebinden türetmek ve istek yükündeki herhangi bir rol alanını yok saymak.
10. IF Agent_Backend'in türettiği Role değeri istenen Permission'ı içermiyorsa, THEN THE Agent_Backend SHALL isteği işlemeden "Bu işlem için yetkiniz yok" yanıtını döndürmek ve Requirement 4.5'teki denetim kaydını yazmak.
11. THE `agentcore/agentcore.json` dosyası SHALL çalışma zamanı rolüne ek AWS izinleri gerektiğinde bu izinleri yalnızca `additionalPolicies` listesi üzerinden tanımlamak; IAM rolleri elle düzenlenmemelidir.
12. WHERE Streamlit_Client barındırma hedefi olarak yerel çalıştırma veya konteyner seçilebilir, THE Logistics_AI_App SHALL bu hedeflerden hiçbirini zorunlu kılmamak.

### Requirement 14: README Belgesi

**User Story:** Bir geliştirici olarak, projeyi kurmayı, çalıştırmayı ve dağıtmayı anlatan Türkçe bir README istiyorum, böylece projeye hızlıca başlayabilirim.

#### Acceptance Criteria

1. THE Logistics_AI_App SHALL `Logistic_AI/README.md` dosyasını Türkçe olarak içermek.
2. THE README SHALL şu bölümleri içermek: proje amacı, mimari ve dağıtım topolojisi, klasör yapısı, ön koşullar, Cognito kurulumu, gerekli ortam değişkenleri, yerel çalıştırma, dağıtım, dağıtılmış ajanı çağırma, durum/günlük/izleme komutları, sorun giderme tablosu, güvenlik notları ve gelecek kapsam.
3. THE README ön koşullar bölümü SHALL Node.js 20.12 veya üzeri, Python 3.12 veya üzeri, uv, AWS CDK, AgentCore_CLI 1.0.3 ve Bedrock ile AgentCore erişimi olan yapılandırılmış AWS kimlik bilgilerini listelemek.
4. THE README Cognito kurulumu bölümü SHALL kullanıcı havuzu oluşturmayı, `USER_PASSWORD_AUTH` akışı etkin bir App Client oluşturmayı ve `SUPPLIER`, `MATERIAL_RESPONSIBLE` ile `TRANSPORT_OFFICE` adlı üç grubu oluşturmayı anlatmak.
5. THE README ortam değişkenleri bölümü SHALL yalnızca değişken adlarını listelemek ve hiçbir gerçek değer, şifre veya token içermemek.
6. THE README yerel çalıştırma bölümü SHALL `agentcore dev --port 8081` komutunu, `agentcore invoke --runtime agent --local --port 8081 --payload '{"prompt":"..."}'` komutunu ve Streamlit_Client çalıştırma komutunu içermek ve 8080 numaralı bağlantı noktasının kullanılmaması gerektiğini belirtmek.
7. THE README dağıtım bölümü SHALL `agentcore deploy` komutunu ve ilk dağıtımın yaklaşık 5 ile 8 dakika sürdüğünü belirtmek.
8. THE README dağıtılmış ajanı çağırma bölümü SHALL `agentcore invoke --runtime agent --session-id <kimlik> --payload '{"prompt":"..."}'` komutunu ve oturum kimliğinin en az 33 karakter olması gerektiğini belirtmek.
9. THE README durum ve izleme bölümü SHALL `agentcore status`, `agentcore logs runtime --tail` ve `agentcore traces runtime list --since 15m` komutlarını içermek.
10. THE README sorun giderme tablosu SHALL en az şu hataları içermek: 30 saniyelik çalışma zamanı başlatma aşımı, 33 karakterden kısa oturum kimliği, inference profile öneki olmayan model kimliği, ARM64 wheel bulunamaması, izin reddedildi hatası ve 8081 numaralı bağlantı noktasının kullanımda olması.
11. THE README güvenlik notları bölümü SHALL sırların kaynak koda ve sürüm kontrolüne eklenmemesini, IAM rollerinin elle düzenlenmemesini ve yetkilendirmenin Agent_Backend'de zorunlu uygulandığını belirtmek.
12. THE README gelecek kapsam bölümü SHALL Bedrock model çağrıları, Tools, Memory, Skills ve MCP bileşenlerini Faz 1 dışı olarak listelemek.
