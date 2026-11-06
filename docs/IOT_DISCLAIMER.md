# IoT safety and responsibility statement

<!-- IOT_DISCLAIMER_VERSION: 2026-11-03 -->
**Version 2026-11-03** · OpenAmika, MekaHime Inc. · [English](#english) · [日本語](#日本語) · [简体中文](#简体中文) · [한국어](#한국어)

OpenAmika shows this statement on the Tools page before any IoT (smart-home) feature can be turned on, and turns IoT
on only after you tick "I have read and accept this" and press **Enable IoT**. It asks again whenever this statement
changes: the version above changes with it, and IoT stays off until the new version is accepted. The launcher, the
brain and the openamika-iot bridge all refuse to start IoT without that acceptance.

Translation policy (2026-11-06): Korean is a translation of the unchanged English statement, not new terms or
permission. The consent version remains 2026-11-03. Reading or switching a language never records acceptance,
enables a server, or grants a capability. Existing current-version acceptance remains valid; missing or stale
acceptance still requires the person's explicit checkbox and Enable IoT action. A substantive safety or obligation
change must increment the version and ask again. The English original governs if translations differ.

<!-- iot-disclaimer:en -->
## English

**IoT safety and responsibility statement, version 2026-11-03**

**Read all of this before you turn on IoT. If you do not agree with it, do not enable IoT.**

### 1. What this statement covers

"IoT" means every way OpenAmika lets Amika see, switch or change something in the physical world: the Smart Home
and IoT panel on the Tools page, the openamika-iot bridge (servers/openamika-iot), the MQTT broker and zigbee2mqtt
services the launcher can start, Home Assistant's MCP server, and any other MCP server, agent or tool you connect
that can reach a device. "Device" means anything one of these can reach: smart plugs, switches, lights, sensors,
scenes, and whatever is plugged into, wired to or controlled by them.

### 2. Amika is an AI, not a safety system

Amika runs on large language models (LLMs). LLMs are non-deterministic: the same words can lead to a different
answer or a different action from one time to the next, and nobody, including MekaHime, can predict or guarantee
what she will do. In particular, she can:

- mishear you (speech recognition makes mistakes with noise, accents, names and similar-sounding words), or
  misunderstand what you meant;
- act on the wrong device, for example one with a similar name, nickname or note, or one that was renamed,
  re-paired or moved;
- act at the wrong time: too early, too late, or long after you asked;
- repeat an action, skip it, or do only part of it;
- say that something was done when it was not, or that it failed when it did not;
- be manipulated: the words in a conversation, a message, a web page, an email, a document, a video or a song, or
  anything else she reads, hears or sees through the camera, can try to make her act (this is called prompt
  injection), and other people in the room, on a call or in a chat can talk to her too;
- misjudge what a device is, what is plugged into it, or what switching it will do.

Everything she depends on can also fail or behave unexpectedly: the AI models and the companies that provide them,
your internet connection and home network, OpenAmika itself and its bridges, the MQTT broker, zigbee2mqtt, the
Zigbee dongle and radio, Home Assistant or any other integration, and the devices and their firmware. A device can
lose power or its connection, restart in a different state, miss a command, or report the wrong state.

### 3. No guarantee

There is no guarantee that Amika will not cause harm to your IoT devices, to anything connected to them, to your
home or other property, to your data, or to people or animals. OpenAmika's safeguards (she acts only when you ask,
your own words are checked before anything runs, per-tool policies, confirmation steps, device confirmations,
health checks) are best-effort measures that reduce some risks. They are never a guarantee, they can fail, and
nobody's safety may depend on them.

### 4. At your own risk

Everything you connect to Amika's IoT, you connect at your own risk. You alone are responsible for:

- what you connect, and what is plugged into or controlled by it;
- how it is installed, wired, configured, paired, named and secured, including your network, the MQTT broker and
  any accounts and access tokens;
- supervising Amika while IoT is on, checking what she did, and putting things right when she gets it wrong;
- following the instructions, warnings and terms of the device makers and of every service you use;
- complying with the laws, regulations, building codes and electrical-safety rules where you live, and respecting
  the safety and rights of everyone in your home or affected by your devices.

### 5. Do not connect anything dangerous

Do not connect, directly or indirectly, anything that is dangerous, or that could cause danger if it is switched at
the wrong time, left on, turned off, misused or abused. For example, never connect:

- heaters and space heaters, electric blankets, heat lamps and heating pads;
- stoves, cooktops, ovens, toasters, kettles, irons, hair straighteners, soldering irons, 3D printers and any other
  heating or cooking appliance;
- gas valves, water valves, pumps, irrigation, boilers and water heaters;
- door locks and smart locks, garage doors, gates, motorised windows, shutters or blinds, and anything else that
  controls who can get into your home;
- alarms and security systems, cameras, smoke and carbon-monoxide detectors, and anything else that protects people;
- medical, life-support, mobility or health equipment of any kind;
- child- or pet-safety devices: baby monitors, pet feeders, the heaters, pumps and lights of aquariums, terrariums
  and tanks, pet doors, fences;
- vehicles and their chargers, e-bike and scooter chargers, machinery, power tools and industrial equipment;
- high-power loads, or anything near the rated limit of the plug, cable, extension lead or adapter it runs on;
- anything whose failure, unexpected switching, or being left on or off could cause a fire, flooding, an electric
  shock, injury, illness, damage or data loss, or could let someone in.

If you are not sure that something is safe to connect, do not connect it.

### 6. Keep control

- Keep manual, physical control of every connected device: you must always be able to switch it by hand or unplug
  it, without Amika.
- Do not rely on Amika for anything that matters for safety, health, security or property.
- Do not leave IoT running unattended with anything that could cause harm.
- Keep the setting that makes switching wait for your approval ("confirm" on the Tools page) unless you understand
  what changing it means.
- Do not let children, or anyone who has not read and accepted this statement, set up or use Amika's IoT.
- You can turn IoT off at any time: switch off the smart-home server or "Tools enabled" on the Tools page, or stop
  OpenAmika. Turning IoT off stops Amika from reaching your devices; it does not change their current state, so
  check them yourself.

### 7. No warranty, no liability

OpenAmika is provided "as is", without warranty of any kind, express or implied, including but not limited to the
warranties of merchantability, fitness for a particular purpose and non-infringement, as its MIT License says. To
the maximum extent permitted by applicable law, MekaHime Inc. and OpenAmika's contributors are not responsible or
liable for any outcome of using Amika's IoT features, or for any damage, loss or injury arising from or connected
with them, including damage to devices or property, fire, flooding, data loss, financial loss, personal injury or
death, whether in contract, tort (including negligence) or otherwise, even if they were told it could happen.
Where the law does not allow a responsibility to be excluded or limited, it is excluded or limited only as far as
the law allows. This statement adds to the MIT License for the IoT features; it does not take anything away from
it.

### 8. Your acceptance

By ticking "I have read and accept this" and enabling IoT, you confirm that you have read and understood this
statement and accept it, and that you have the right to make decisions about the devices and the home concerned.
OpenAmika records the version you accepted and the time in config/tools.json on your computer; nothing is sent to
MekaHime. If you do not agree, do not enable IoT, and if it is already on, turn it off.

Questions: hi@mekahime.com
<!-- /iot-disclaimer:en -->

<!-- iot-disclaimer:ko -->
## 한국어

**IoT 안전 및 책임 고지, 버전 2026-11-03**

**IoT를 켜기 전에 이 고지 전체를 읽으세요. 동의하지 않으면 IoT를 활성화하지 마세요.**

### 1. 이 고지의 적용 범위

"IoT"는 OpenAmika를 통해 Amika가 실제 세계의 무언가를 확인하거나 켜고 끄거나 변경할 수 있는 모든 경로를 뜻합니다. 도구 페이지의 스마트 홈 및 IoT 패널, openamika-iot 브리지(servers/openamika-iot), 실행기가 시작할 수 있는 MQTT 브로커와 zigbee2mqtt 서비스, Home Assistant의 MCP 서버, 기기에 접근할 수 있도록 연결한 다른 모든 MCP 서버·에이전트·도구가 포함됩니다. "기기"는 이들이 접근할 수 있는 스마트 플러그, 스위치, 조명, 센서, 장면과 여기에 꽂히거나 배선으로 연결되거나 제어되는 모든 것을 뜻합니다.

### 2. Amika는 AI이며 안전 시스템이 아닙니다

Amika는 대규모 언어 모델(LLM)로 작동합니다. LLM은 비결정적입니다. 같은 말이라도 매번 다른 답변이나 행동으로 이어질 수 있으며, MekaHime을 포함해 누구도 Amika의 행동을 예측하거나 보장할 수 없습니다. 특히 다음과 같은 일이 일어날 수 있습니다.

- 말을 잘못 듣거나(음성 인식은 잡음, 억양, 이름, 비슷하게 들리는 단어에서 실수합니다) 의도를 잘못 이해할 수 있습니다.
- 이름·별명·메모가 비슷한 기기나 이름 변경·재페어링·이동한 기기 등 잘못된 기기를 조작할 수 있습니다.
- 너무 이르거나 늦거나 요청한 지 한참 후 등 잘못된 시점에 작동할 수 있습니다.
- 동작을 반복하거나 건너뛰거나 일부만 수행할 수 있습니다.
- 실제로 수행하지 않았는데 완료했다고 하거나 실패하지 않았는데 실패했다고 할 수 있습니다.
- 조종당할 수 있습니다. 대화, 메시지, 웹 페이지, 이메일, 문서, 영상, 노래의 말이나 카메라를 통해 보거나 듣거나 읽는 모든 내용이 행동을 유도할 수 있습니다(이를 프롬프트 인젝션이라고 합니다). 같은 방, 통화 또는 채팅에 있는 다른 사람도 Amika에게 말할 수 있습니다.
- 기기의 정체, 연결된 물건, 전환 동작의 결과를 잘못 판단할 수 있습니다.

Amika가 의존하는 모든 요소도 고장 나거나 예상과 다르게 작동할 수 있습니다. AI 모델과 이를 제공하는 회사, 인터넷 연결과 가정 네트워크, OpenAmika 자체와 브리지, MQTT 브로커, zigbee2mqtt, Zigbee 동글과 무선 통신, Home Assistant나 다른 연동, 기기와 펌웨어가 모두 해당합니다. 기기가 전원이나 연결을 잃거나 다른 상태로 재시작하거나 명령을 놓치거나 잘못된 상태를 보고할 수 있습니다.

### 3. 안전을 보장하지 않습니다

Amika가 IoT 기기, 연결된 물건, 집이나 다른 재산, 데이터, 사람이나 동물에 해를 끼치지 않는다고 보장하지 않습니다. OpenAmika의 보호 장치(요청한 경우에만 행동, 실행 전 사용자의 말 확인, 도구별 정책, 승인 단계, 기기 확인, 상태 점검)는 일부 위험을 줄이려는 최선의 노력일 뿐입니다. 결코 보장이 아니며 실패할 수 있습니다. 누구의 안전도 여기에 의존해서는 안 됩니다.

### 4. 위험은 본인이 부담합니다

Amika의 IoT에 연결하는 모든 것은 본인의 위험 부담으로 연결합니다. 다음 사항은 전적으로 본인의 책임입니다.

- 무엇을 연결하고 그 기기에 무엇이 꽂히거나 제어되는지 확인하는 일.
- 네트워크, MQTT 브로커, 계정과 접근 토큰을 포함하여 설치·배선·설정·페어링·이름 지정·보안을 관리하는 일.
- IoT가 켜져 있는 동안 Amika를 감독하고 수행한 일을 확인하며 잘못되면 바로잡는 일.
- 기기 제조사와 이용하는 모든 서비스의 지침·경고·약관을 따르는 일.
- 거주 지역의 법률·규정·건축 기준·전기 안전 규칙을 준수하고 집 안의 사람이나 기기의 영향을 받는 모든 사람의 안전과 권리를 존중하는 일.

### 5. 위험한 것은 연결하지 마세요

위험한 물건 또는 잘못된 시점에 켜고 끄거나 켜 둔 채 방치하거나 오용·악용하면 위험해질 수 있는 물건을 직간접적으로 연결하지 마세요. 예를 들어 다음은 절대 연결하지 마세요.

- 난방기와 보조 난방기, 전기 담요, 열 램프, 온열 패드.
- 스토브, 조리대, 오븐, 토스터, 주전자, 다리미, 헤어 고데기, 납땜 인두, 3D 프린터와 그 밖의 모든 가열·조리 기기.
- 가스 밸브, 수도 밸브, 펌프, 관개 장치, 보일러, 온수기.
- 문 잠금장치와 스마트 잠금장치, 차고 문, 대문, 전동 창문·셔터·블라인드와 집에 들어올 수 있는 사람을 통제하는 모든 물건.
- 경보기와 보안 시스템, 카메라, 연기·일산화탄소 감지기와 사람을 보호하는 모든 물건.
- 모든 종류의 의료·생명 유지·이동 보조·건강 관리 장비.
- 아동·반려동물 안전 기기: 아기 모니터, 자동 급식기, 수족관·테라리움·사육장의 히터·펌프·조명, 반려동물 출입문, 울타리.
- 차량과 충전기, 전기 자전거·킥보드 충전기, 기계, 전동 공구, 산업 장비.
- 고전력 부하 또는 사용하는 플러그·케이블·연장선·어댑터의 정격 한계에 가까운 부하.
- 고장, 예기치 않은 전환, 켜지거나 꺼진 채 방치됨으로 인해 화재·침수·감전·부상·질병·손상·데이터 손실이 발생하거나 누군가 침입할 수 있게 되는 모든 물건.

연결해도 안전한지 확신할 수 없다면 연결하지 마세요.

### 6. 직접 제어할 수 있어야 합니다

- 연결된 모든 기기에 대한 수동·물리적 제어 수단을 유지하세요. Amika 없이도 언제나 손으로 켜고 끄거나 플러그를 뽑을 수 있어야 합니다.
- 안전·건강·보안·재산에 중요한 일은 Amika에 의존하지 마세요.
- 해를 끼칠 수 있는 물건이 연결된 상태에서 IoT를 감독 없이 작동시키지 마세요.
- 설정 변경의 의미를 이해하지 못한다면, 전환 전에 승인을 기다리게 하는 설정(도구 페이지의 "confirm")을 유지하세요.
- 어린이나 이 고지를 읽고 동의하지 않은 사람이 Amika의 IoT를 설정하거나 사용하게 하지 마세요.
- IoT는 언제든지 끌 수 있습니다. 도구 페이지에서 스마트 홈 서버나 "도구 활성화"를 끄거나 OpenAmika를 종료하세요. IoT를 끄면 Amika가 기기에 접근하지 못하지만 기기의 현재 상태는 바뀌지 않으므로 직접 확인하세요.

### 7. 보증 및 책임의 부인

OpenAmika는 MIT 라이선스에 명시된 대로 상품성, 특정 목적에의 적합성, 비침해성을 포함하되 이에 한정되지 않는 어떠한 명시적·묵시적 보증도 없이 "있는 그대로" 제공됩니다. 관련 법률이 허용하는 최대 범위에서 MekaHime Inc.와 OpenAmika 기여자는 Amika의 IoT 기능 사용 결과나 이와 관련해 발생한 손해·손실·부상에 책임을 지지 않습니다. 기기·재산 손상, 화재, 침수, 데이터 손실, 금전적 손실, 신체 상해, 사망을 포함하며, 계약·불법행위(과실 포함) 또는 그 밖의 사유인지, 발생 가능성을 미리 통지받았는지와 관계없습니다. 법률이 책임의 배제나 제한을 허용하지 않는 경우에는 법률이 허용하는 범위에서만 배제하거나 제한합니다. 이 고지는 IoT 기능에 관하여 MIT 라이선스를 보완하며 그 내용을 축소하지 않습니다.

### 8. 사용자의 동의

"이 고지를 읽었으며 동의합니다"를 선택하고 IoT를 활성화하면 이 고지를 읽고 이해하고 동의했으며 해당 기기와 집에 관해 결정할 권한이 있음을 확인하는 것입니다. OpenAmika는 동의한 버전과 시각을 본인의 컴퓨터에 있는 config/tools.json에 기록하며 MekaHime에 전송하지 않습니다. 동의하지 않으면 IoT를 활성화하지 말고, 이미 켜져 있으면 끄세요. 이 번역과 영어 원문이 다르면 영어 원문이 우선합니다. 번역을 읽거나 언어를 바꾸는 것만으로는 동의가 기록되거나 권한이 부여되지 않습니다.

문의: hi@mekahime.com
<!-- /iot-disclaimer:ko -->

<!-- iot-disclaimer:ja -->
## 日本語

**IoT の安全と責任に関する声明（バージョン 2026-11-03）**

この日本語訳は参考のためのものです。英語版と内容が異なる場合は、英語版が優先します。

**IoT を有効にする前に、この声明をすべてお読みください。同意できない場合は、IoT を有効にしないでください。**

### 1. この声明の対象

ここでいう「IoT」とは、OpenAmika を通じて Amika が現実世界のものを確認し、切り替え、または変更できるようにするすべての手段を指します。Tools ページの「Smart Home and IoT」パネル、openamika-iot ブリッジ（servers/openamika-iot）、ランチャーが起動できる MQTT ブローカーと zigbee2mqtt のサービス、Home Assistant の MCP サーバー、そしてデバイスに届くその他の MCP サーバー、エージェント、ツールがすべて含まれます。「デバイス」とは、これらが届くすべてのもの、つまりスマートプラグ、スイッチ、照明、センサー、シーン、そしてそれらに差し込まれ、配線され、またはそれらによって制御されているすべてのものを指します。

### 2. Amika は AI であり、安全装置ではありません

Amika は大規模言語モデル（LLM）で動いています。LLM は非決定的です。同じ言葉でも、そのときによって異なる返答や異なる動作につながることがあり、MekaHime を含め誰も、Amika が何をするかを予測することも保証することもできません。特に、Amika には次のようなことが起こりえます。

- あなたの言葉を聞き間違える（音声認識は、雑音、なまり、名前、発音の似た言葉で誤ります）、またはあなたの意図を誤解する。
- 違うデバイスを操作する。たとえば名前、ニックネーム、メモが似ているデバイスや、名前の変更、再ペアリング、移動をしたデバイス。
- 間違ったタイミングで操作する。早すぎる、遅すぎる、または頼んでからずっと後になって操作する。
- 操作を繰り返す、飛ばす、または一部しか実行しない。
- 実行していないのに実行したと言う、または成功したのに失敗したと言う。
- 誘導される。会話、メッセージ、ウェブページ、メール、文書、動画、歌の言葉など、Amika が読み、聞き、またはカメラで見るあらゆるものが、Amika に何かをさせようとすることがあります（これをプロンプトインジェクションといいます）。同じ部屋にいる人や、通話やチャットの相手も Amika に話しかけることができます。
- デバイスが何であるか、何がつながっているか、切り替えると何が起きるかを取り違える。

Amika が依存しているものも、故障したり予期しない動作をしたりすることがあります。AI モデルとそれを提供する事業者、インターネット接続と家庭内ネットワーク、OpenAmika 本体とそのブリッジ、MQTT ブローカー、zigbee2mqtt、Zigbee ドングルと無線、Home Assistant などの連携先、そしてデバイスとそのファームウェアです。デバイスは電源や接続を失ったり、別の状態で再起動したり、コマンドを受け取り損ねたり、誤った状態を報告したりすることがあります。

### 3. 保証はありません

Amika があなたの IoT デバイス、それにつながっているもの、住まいその他の財産、データ、または人や動物に害を与えないという保証はありません。OpenAmika の安全策（あなたが頼んだときにだけ動くこと、実行前にあなた自身の言葉を照合すること、ツールごとのポリシー、確認の手順、デバイスからの確認応答、ヘルスチェック）は、一部のリスクを減らすための最善努力の措置にすぎません。それらは決して保証ではなく、失敗することもあり、誰の安全もそれに頼ってはなりません。

### 4. 自己責任でのご利用

Amika の IoT に接続するものは、すべてあなた自身の責任で接続するものです。次のことについては、あなただけが責任を負います。

- 何を接続するか、そしてそれに何が差し込まれ、何がそれによって制御されているか。
- 設置、配線、設定、ペアリング、名前付け、セキュリティ対策の方法（ネットワーク、MQTT ブローカー、各種アカウントとアクセストークンを含みます）。
- IoT を有効にしている間 Amika を見守り、Amika が何をしたかを確認し、間違えたときには元に戻すこと。
- デバイスのメーカーと、利用するすべてのサービスの説明書、警告、利用規約に従うこと。
- お住まいの地域の法令、規則、建築基準、電気安全に関するルールを守り、同居するすべての人とデバイスの影響を受けるすべての人の安全と権利を尊重すること。

### 5. 危険なものは接続しないでください

危険なもの、または間違ったタイミングでの切り替え、つけっぱなし、電源オフ、誤用や悪用によって危険を生じうるものを、直接にも間接にも接続しないでください。たとえば、次のものは決して接続しないでください。

- 暖房器具や電気ストーブなどのヒーター、電気毛布、ヒートランプ、ヒーターマット。
- コンロ、IH 調理器、オーブン、トースター、電気ケトル、アイロン、ヘアアイロン、はんだごて、3D プリンター、その他の加熱器具や調理器具。
- ガス栓やガスのバルブ、水のバルブ、ポンプ、散水装置、ボイラー、給湯器。
- ドアの錠やスマートロック、ガレージのドア、門扉、電動の窓・シャッター・ブラインド、その他家に誰が入れるかを左右するもの。
- 警報装置やセキュリティシステム、カメラ、煙や一酸化炭素の検知器、その他人を守るもの。
- あらゆる種類の医療機器、生命維持装置、移動補助機器、健康関連機器。
- 子どもやペットの安全に関わる機器：ベビーモニター、ペットの給餌器、水槽やテラリウムのヒーター・ポンプ・照明、ペットドア、柵。
- 車両とその充電器、電動自転車や電動キックボードの充電器、機械、電動工具、産業用機器。
- 消費電力の大きい機器、または使用するプラグ、ケーブル、延長コード、アダプターの定格の上限に近いもの。
- 故障、予期しない切り替え、つけっぱなしや切れたままになることによって、火災、浸水、感電、けが、病気、損害、データの消失を引き起こしうるもの、または誰かを家に入れてしまいうるもの。

接続しても安全だと確信できないものは、接続しないでください。

### 6. 操作の主導権を保ってください

- 接続したすべてのデバイスについて、手動で物理的に操作できる手段を確保してください。Amika を介さずに、いつでも手で切り替えたり、プラグを抜いたりできなければなりません。
- 安全、健康、防犯、財産に関わることを Amika に頼らないでください。
- 害を生じうるものがつながった状態で、IoT を人のいないまま動かし続けないでください。
- 切り替えの前にあなたの承認を待つ設定（Tools ページの「confirm」）は、変更の意味を理解していない限り、そのままにしてください。
- 子どもや、この声明を読んで同意していない人に、Amika の IoT を設定させたり使わせたりしないでください。
- IoT はいつでもオフにできます。Tools ページでスマートホームのサーバーまたは「Tools enabled」をオフにするか、OpenAmika を停止してください。IoT をオフにすると Amika はデバイスに届かなくなりますが、デバイスの現在の状態は変わりません。ご自身で確認してください。

### 7. 無保証・責任の制限

OpenAmika は、その MIT ライセンスに定めるとおり「現状のまま」提供され、商品性、特定目的への適合性および権利の非侵害についての保証を含め（ただしこれらに限られません）、明示か黙示かを問わず、いかなる保証もありません。適用される法令が認める最大限の範囲で、MekaHime Inc. および OpenAmika の貢献者は、Amika の IoT 機能を使用した結果について、またそれに起因し、または関連して生じたいかなる損害、損失、傷害（デバイスや財産の損傷、火災、浸水、データの消失、金銭的損失、人身傷害、死亡を含みます）についても、契約、不法行為（過失を含みます）その他いかなる法的根拠によるかを問わず、その可能性を知らされていた場合であっても、責任を負いません。法令上、責任の排除または制限が認められない場合は、法令が認める範囲でのみ排除または制限されます。この声明は、IoT 機能について MIT ライセンスに付け加えるものであり、MIT ライセンスの内容を何ら減じるものではありません。

### 8. 同意について

「I have read and accept this」（これを読み、同意します）にチェックを入れて IoT を有効にすることにより、あなたは、この声明を読んで理解し、同意したこと、そして対象となるデバイスと住まいについて決める権利があることを確認したものとします。OpenAmika は、同意したバージョンと日時をあなたのコンピューターの config/tools.json に記録します。MekaHime には何も送信されません。同意できない場合は IoT を有効にしないでください。すでに有効にしている場合は、オフにしてください。

お問い合わせ：hi@mekahime.com
<!-- /iot-disclaimer:ja -->

<!-- iot-disclaimer:zh -->
## 简体中文

**IoT 安全与责任声明（版本 2026-11-03）**

本中文译文仅供参考；如与英文版本有任何不一致，以英文版本为准。

**开启 IoT 之前，请完整阅读本声明。如果你不同意，请不要开启 IoT。**

### 1. 本声明的适用范围

这里的“IoT”指 OpenAmika 让 Amika 查看、开关或改变现实世界中任何事物的所有方式：Tools 页面上的“Smart Home and IoT”面板、openamika-iot 桥接程序（servers/openamika-iot）、启动器可以启动的 MQTT 代理（broker）和 zigbee2mqtt 服务、Home Assistant 的 MCP 服务器，以及你接入的、能够触及设备的任何其他 MCP 服务器、智能体或工具。“设备”指上述任何一种方式能够触及的一切：智能插座、开关、灯、传感器、场景，以及插在它们上面、接在它们上面或由它们控制的一切。

### 2. Amika 是 AI，不是安全系统

Amika 由大语言模型（LLM）驱动。大语言模型具有不确定性（非确定性）：同样的话，这一次和下一次可能带来不同的回答或不同的操作；包括 MekaHime 在内，任何人都无法预测或保证她会做什么。具体来说，她可能会：

- 听错你的话（在有噪音、口音、人名或发音相近的词时，语音识别会出错），或者误解你的意思；
- 操作错误的设备，例如名称、昵称或备注相近的设备，或者被重命名、重新配对或移动过的设备；
- 在错误的时间操作：太早、太晚，或者在你提出要求很久之后；
- 重复一个操作、跳过它，或者只完成其中一部分；
- 明明没有做却说已经做了，或者明明成功了却说失败了；
- 被操纵：对话、消息、网页、邮件、文档、视频或歌曲中的文字，或者她读到、听到、通过摄像头看到的任何其他内容，都可能试图诱导她采取行动（这称为“提示词注入”）；同一房间里的人、通话或聊天中的其他人也可以对她说话；
- 误判一个设备是什么、上面接着什么，或者开关它会带来什么后果。

她所依赖的一切也都可能出故障或出现意外行为：AI 模型和提供这些模型的公司、你的互联网连接和家庭网络、OpenAmika 本身及其桥接程序、MQTT 代理、zigbee2mqtt、Zigbee USB 适配器和无线信号、Home Assistant 或其他任何集成，以及设备本身和它们的固件。设备可能断电或断网、重启后处于不同的状态、漏掉一条指令，或者报告错误的状态。

### 3. 不作任何保证

我们不保证 Amika 不会对你的 IoT 设备、与之相连的任何东西、你的住所或其他财产、你的数据，或者人或动物造成伤害。OpenAmika 的各项安全措施（只在你提出要求时才行动、执行前核对你本人说过的话、按工具设定的策略、确认步骤、设备回执、健康检查）只是尽力降低部分风险的措施。它们绝不是保证，也可能失效，任何人的安全都不能依赖它们。

### 4. 风险由你自行承担

你接入 Amika IoT 的一切，风险均由你自行承担。以下事项完全由你负责：

- 接入什么，以及插在上面或由它控制的是什么；
- 如何安装、接线、配置、配对、命名和保护它们，包括你的网络、MQTT 代理以及任何账户和访问令牌；
- 在 IoT 开启期间看管 Amika，检查她做了什么，并在她出错时加以纠正；
- 遵守设备制造商以及你所使用的每一项服务的说明、警告和条款；
- 遵守你所在地的法律法规、建筑规范和用电安全规定，并尊重你家中每一个人以及受你的设备影响的每一个人的安全和权利。

### 5. 不要接入任何危险的东西

不要直接或间接接入任何危险的东西，或者在错误的时间被开关、一直开着、被关掉、被误用或被滥用时可能引发危险的东西。例如，绝对不要接入：

- 取暖器和电暖器、电热毯、加热灯和加热垫；
- 炉灶、电磁炉、烤箱、烤面包机、电水壶、熨斗、直发器、电烙铁、3D 打印机，以及其他任何加热或烹饪电器；
- 燃气阀门、水阀、水泵、灌溉设备、锅炉和热水器；
- 门锁和智能锁、车库门、大门、电动窗、电动卷帘或百叶窗，以及其他任何决定谁能进入你家的东西；
- 报警器和安防系统、摄像头、烟雾和一氧化碳报警器，以及其他任何保护人身安全的东西；
- 任何医疗、生命维持、助行或健康设备；
- 涉及儿童或宠物安全的设备：婴儿监视器、宠物喂食器，鱼缸、爬宠箱和水族箱的加热器、水泵和灯，宠物门、围栏；
- 车辆及其充电器、电动自行车和电动滑板车的充电器、机械设备、电动工具和工业设备；
- 大功率负载，或者接近其所用插座、线缆、延长线（插线板）或转换器额定上限的东西；
- 任何一旦出故障、被意外开关、一直开着或一直关着，就可能引发火灾、水浸、触电、受伤、疾病、损坏或数据丢失，或者可能让人进入你家的东西。

如果你不能确定某样东西接入后是安全的，就不要接入。

### 6. 保留控制权

- 对每一个接入的设备都保留手动、物理上的控制：你必须随时能够不经过 Amika，用手开关它或者拔掉插头。
- 不要在任何关系到安全、健康、安防或财产的事情上依赖 Amika。
- 接着任何可能造成伤害的东西时，不要让 IoT 在无人看管的情况下运行。
- 除非你明白改动意味着什么，否则请保留“开关前等待你批准”的设置（Tools 页面上的“confirm”）。
- 不要让儿童，或者没有阅读并接受本声明的人，设置或使用 Amika 的 IoT。
- 你可以随时关闭 IoT：在 Tools 页面关闭智能家居服务器或“Tools enabled”，或者停止 OpenAmika。关闭 IoT 后，Amika 就无法再触及你的设备，但这不会改变设备当前的状态，请你自己检查。

### 7. 不作担保，不承担责任

正如 OpenAmika 的 MIT 许可证所述，OpenAmika 按“原样”提供，不附带任何明示或默示的担保，包括但不限于适销性、特定用途适用性和不侵权的担保。在适用法律允许的最大范围内，对于使用 Amika IoT 功能所产生的任何后果，以及由此引起或与之相关的任何损害、损失或伤害（包括设备或财产损坏、火灾、水浸、数据丢失、经济损失、人身伤害或死亡），无论基于合同、侵权（包括过失）还是其他法律依据，即使已被告知可能发生，MekaHime Inc. 和 OpenAmika 的贡献者均不承担任何责任。如果法律不允许排除或限制某项责任，则仅在法律允许的范围内予以排除或限制。本声明是在 IoT 功能方面对 MIT 许可证的补充，并不减损 MIT 许可证的任何内容。

### 8. 你的同意

勾选“I have read and accept this”（我已阅读并接受）并开启 IoT，即表示你确认已经阅读、理解并接受本声明，并且有权就相关设备和住所作出决定。OpenAmika 会把你接受的版本和时间记录在你电脑上的 config/tools.json 中，不会向 MekaHime 发送任何内容。如果你不同意，请不要开启 IoT；如果已经开启，请将其关闭。

如有疑问：hi@mekahime.com
<!-- /iot-disclaimer:zh -->
