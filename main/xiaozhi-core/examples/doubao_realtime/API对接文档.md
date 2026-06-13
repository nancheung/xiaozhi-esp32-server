<span id="5cee3196"></span>

# 1 接口功能

豆包端到端实时语音大模型API即RealtimeAPI支持低延迟、多模式交互，可用于构建语音到语音的对话工具。该API支持中文和英语两大语种，目前只支持WebSocket协议连接到此API，同时支持客户边发送数据边接收数据的流式交互方式。

<span id="3a15e6c1"></span>

## 1.1 产品约束

1. 不同端到端模型版本的功能差异如下所示，其中未特别标注的功能，均为所有版本通用支持

| 功能 | O版本 | O2.0版本 | SC版本 | SC2.0版本 |
|---|---|---|---|---|
| 精品音色（vv、xiaohe、yunzhou、xiaotian） | ✅ | ✅ | ❌ | ❌ |
| System Prompt开放配置 | ✅ | ✅ | ✅ | ✅ |
| 克隆音色（`ICL_`或者`S_`开头的音色名称） | ❌ | ❌ | ✅ | ❌ |
| 克隆音色2.0（`saturn_`或者`S_`开头的音色名称） | ❌ | ✅ | ❌ | ✅ |
| 模型最大上下文长度 | —— | 12K | —— | 12K |

* O 版本代表 Omni，多模态模型路线；SC 版本代表 Strong Character，角色扮演模型路线，主要强化人设表达和拟人化互动能力
    * 当前 O 版本与 SC 版本已停止独立迭代维护，产品能力将逐步收敛至对应的 2.0 版本，并以后者作为后续主推方向
* O版本和SC版本都支持客户配置System Prompt，但是具体的配置字段会存在差异：
    * O版本以及O2.0版本可以配置bot_name、system_role、speaking_style字段，参考人设部分
    * SC版本以及SC2.0版本可以配置character_manifest字段，参考角色描述部分
* O2.0 版本相较于 O 版本的主要优化点：
    * **整体能力升级**：显著提升模型的推理能力与基础语音理解、生成能力
    * **唱歌能力增强**：引入合规版权曲库，支持更高质量、更丰富的演唱表现
    * **音频级热修复**：支持在线修复 TN 转写与发音问题，提升问题响应效率，降低版本发布依赖。
* SC2.0 版本相较于 SC 版本的主要优化点：
    * **角色演绎能力提升**：显著增强模型的角色塑造与拟人化表达能力
    * **角色控制能力增强**：完善角色控制指令体系，模型输出文本可包含角色相关的动作与表情描述
    * **音色克隆能力升级**：提升音色克隆的相似度与稳定性
    * **音频级热修复**：支持在线修复 TN 转写与发音问题，提升问题响应效率，降低版本发布依赖。

2. 客户端上传音频格式要求PCM（脉冲编码调制，未经压缩的的音频格式）、单声道、采样率16000、每个采样点用`int16`表示、字节序为小端序。
    1. 除此之外，工程链路升级支持客户端**麦克风输入**音频opus格式，服务内部会转为pcm格式再进行识别处理

```json
{
    "asr": {
        "audio_info": {
            "format": "speech_opus",
            "sample_rate": 16000,
            "channel": 1
        }
    }
}
```

3. 服务端默认返回的是 OGG 封装的 Opus 音频，兼顾压缩效率与传输性能
4. 若客户端在 StartSession事件中增加TTS配置，服务端可返回 PCM 格式的音频流。具体请求参数如下所示：
    * 单声道、24000Hz 采样率、32bit位深、字节序为小端序；

```json
{
    "tts" : {
        "audio_config": {
            "channel": 1,
            "format": "pcm",
            "sample_rate": 24000
        }
    }
}
```

* 单声道、24000Hz 采样率、16bit位深、字节序为小端序；

```json
{
    "tts" : {
        "audio_config": {
            "channel": 1,
            "format": "pcm_s16le",
            "sample_rate": 24000
        }
    }
}
```

5. 端到端模型O版本服务端已新增 4 个音色（O2.0版本音色名称保持不变），客户端需在 StartSession事件中的TTS 配置指定对应的发音人，默认为vv音色。
    1. zh_female_vv_jupiter_bigtts：对应vv音色，活泼灵动的女声，有很强的分享欲
    2. zh_female_xiaohe_jupiter_bigtts：对应xiaohe音色，甜美活泼的女声，有明显的台湾口音
    3. zh_male_yunzhou_jupiter_bigtts：对应yunzhou音色，清爽沉稳的男声
    4. zh_male_xiaotian_jupiter_bigtts：对应xiaotian音色，清爽磁性的男声
    5. en_male_tim_uranus_bigtts：Tim，美式英语，仅支持O2.0版本
    6. en_female_dacey_uranus_bigtts：Dacey，美式英语，仅支持O2.0版本
    7. en_female_stokie_uranus_bigtts：Stokie，美式英语，仅支持O2.0版本

```json
{
    "tts": {
        "speaker": {{STRING}}
    }
}
```

6. 端到端模型SC版本服务端新增21个官方克隆音色，客户端在使用这些音色时候需要在StartSession事件中的TTS 配置指定对应的克隆音色。同时，角色描述在服务端已经配置好了，客户端在请求API时候无需配置character_manifest字段。

   [SC-2.0版本音色列表可点击此处查看](https://www.volcengine.com/docs/6561/1257544?lang=zh#%E7%AB%AF%E5%88%B0%E7%AB%AF%E5%AE%9E%E6%97%B6%E8%AF%AD%E9%9F%B3%E5%A4%A7%E6%A8%A1%E5%9E%8B-s2s-o%E7%89%88%E6%9C%AC%E5%92%8Csc-2-0%E7%89%88%E6%9C%AC-%E9%9F%B3%E8%89%B2%E5%88%97%E8%A1%A8)

7. 除了官方克隆音色之外，客户还可以在火山豆包语音控制台开通、上传音频训练自定义克隆音色等功能。
    1. 购买入口
        1. SC版本在豆包端到端实时语音大模型商品里面

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/c7689678cd6440dd87af29668de30ae4~tplv-goo7wpa0wc-image.image" width="2788px" /></div>

        2. SC2.0版本在豆包声音复刻模型2.0商品里面，在这里购买的音色能同时用于tts和实时语音

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/5e128741d59e435ca315bd362870d5a1~tplv-goo7wpa0wc-image.image" width="2784px" /></div>

        3. 需要注意的是：购买克隆音色之后目前是分钟级生效，即2分钟之后才可以发起音色注册请求
    2. 注册克隆音色[参考文档](https://www.volcengine.com/docs/6561/1305191)，和传统的声音复刻相比有如下注意事项：
        1. 端到端模型仅对中文有较好支持，其他语种效果暂时还不能保证
        2. 在端到端模型里注册克隆音色时候，**强烈推荐**带上对应的音频文本，保证模型克隆效果。另外，需要注意的是，训练音频对应的文本会在合成时候带到System Prompt里面提升克隆效果
        3. 注册端到端模型的复刻音色请求所需参数，未提及参数对端到端链路不生效无需填写
            1. {{Resource-Id}}： SC版本填写seed-icl-1.0；SC2.0版本填写seed-icl-2.0
            2. model_type参数SC版本无需填写；SC2.0版本需填写4

```bash
curl -L -X POST 'https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload' \
-H 'Authorization: Bearer; your-access-key' \
-H 'Resource-Id: {{Resource-Id}}' \
-H 'Content-Type: application/json' \
-d '{
    "speaker_id": "S_123456",
    "appid": "12345678",
    "audios": [
        {
            "audio_bytes": "必填，二进制音频字节，需对二进制音频进行base64编码",
            "text":"必填，音频所对应的文本，可以让用户按照该文本念诵，服务会对比音频与该文本的差异。若差异过大会返回1109 WERError",
            "audio_format": "wav"
        }
    ],
    "model_type": 4,
    "source": 2
}'
```

> 注：`"model_type": 4` 该参数仅SC2.0版本音色需要

8. 限流条件分为QPM和TPM，QPM全称query per minute，这里的query对应StartSession事件，即在一个AppID下面每分钟的StartSession事件不能超过配额值（默认60QPM）。TPM全称tokens per minute，即一分钟所消耗的全部token不能超过对应的配额值（默认10wTPM）。

<span id="45052d94"></span>

## 1.2 最佳实践

1. 系统最初仅支持麦克风输入，现已逐步扩展，支持文本和录音文件作为输入源。具体说明如下：
    1. **麦克风输入**
        1. 采用流式输入输出架构，音频会实时上传，推荐20ms一包发送服务端
        2. 客户端无需额外发送静音片段
    2. **麦克风（包含静音按键）输入**
        1. 麦克风正常打开时候流式输入，音频实时上传【**强烈推荐**】20ms一包发送服务端
        2. 麦克风静音时候无法上传音频到服务端，需要指定如下参数避免音频流超时报错

            ```json
            {
                "dialog": {
                    "extra": {
                        "input_mod": "keep_alive"
                    }
                }
            }
            ```

    3. **麦克风按键输入**
        1. 产品交互形态为按下麦克风按键开始收音，音频实时上传【**强烈推荐**】20ms一包发送服务端
        2. 此模式下无需补充静音，同时屏蔽掉服务端VAD，即依赖客户端告诉服务端音频发送结束，需要指定如下参数才会生效：

            ```json
            {
                "dialog": {
                    "extra": {
                        "input_mod": "push_to_talk"
                    }
                }
            }
            ```

    4. **纯文本输入**
        1. 支持直接以文本形式发起对话。
        2. 服务端会自动补充静音片段，保证流式链路的完整性。

            ```json
            {
                "dialog": {
                    "extra": {
                        "input_mod": "text"
                    }
                }
            }
            ```

    5. **录音文件输入**
        1. 支持将录音文件作为输入源，但是需要将录音文件改为流式发送，【**强烈推荐**】发送20ms的音频包休眠20ms。
        2. 对于采样率 16k、位深 int16 的pcm音频而言，20ms 的音频包大小为 640 字节。
        3. 服务端同样会自动补充静音片段，保持与麦克风实时流式输入一致的处理逻辑。

            ```json
            {
                "dialog": {
                    "extra": {
                        "input_mod": "audio_file"
                    }
                }
            }
            ```

2. 在客户端发送 FinishSession 事件后，系统将不再返回任何事件。但客户端仍可复用与火山语音网关之间的 WebSocket 连接。若需发起新的会话，客户端需重新从 StartSession 事件开始。

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/62445c1d35494378bc96c4ba90a79bb9~tplv-goo7wpa0wc-image.image" width="500px" /></div>

3. 在没有对话需求时候，可以发送FinishSession事件结束会话。如果不想复用websocket连接，可以继续发送FinishConnection事件，释放对应的websocket连接。
4. 推荐客户端在事件的 optional 字段中携带 event 和 session ID，以降低开发成本，并将事件处理的复杂性交由火山语音服务端负责。

<span id="cc8a505d"></span>

# 2 接口说明

WebSocket是一种广泛支持的实时数据传输API，也是服务器应用程序中连接到豆包端到端实时语音大模型API的最佳选择。在客户服务器上集成此API时候，可以通过WebSocket直接连接到实时语音大模型API，具体鉴权参数可以在火山控制台获取。

<span id="61eee5fb"></span>

## 2.1 ws连接详细信息

通过WebSocket建立连接需要以下连接信息：

<table>
<thead>
<tr>
<th></th>
<th>Key</th>
<th>说明</th>
<th>是否必须</th>
<th>Value示例</th>
</tr>
</thead>
<tbody>
<tr>
<td><strong>URL</strong></td>
<td colspan="4"><code>wss://openspeech.bytedance.com/api/v3/realtime/dialogue</code></td>
</tr>
<tr>
<td rowspan="5"><strong>Request Headers</strong></td>
<td>X-Api-App-ID</td>
<td>使用火山引擎控制台获取的APP ID，可参考 <a href="https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F">控制台使用FAQ-Q1</a></td>
<td>是</td>
<td>123456789</td>
</tr>
<tr>
<td>X-Api-Access-Key</td>
<td>使用火山引擎控制台获取的Access Token，可参考 <a href="https://www.volcengine.com/docs/6561/196768#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F">控制台使用FAQ-Q1</a></td>
<td>是</td>
<td>your-access-key</td>
</tr>
<tr>
<td>X-Api-Resource-Id</td>
<td>表示调用服务的资源信息 ID，固定值：volc.speech.dialog</td>
<td>是</td>
<td>volc.speech.dialog</td>
</tr>
<tr>
<td>X-Api-App-Key</td>
<td>固定值</td>
<td>是</td>
<td>PlgvMymc7f3tQnJ6</td>
</tr>
<tr>
<td>X-Api-Connect-Id</td>
<td>用于追踪当前连接情况的标志 ID，建议用户传递，便于排查连接情况</td>
<td>否</td>
<td>d1dcd999-9a9e-4ed6-b227-8649e946f6c4</td>
</tr>
</tbody>
</table>

在 websocket 握手成功后，会返回如下Response header：

| Key | 说明 | Value示例 |
|---|---|---|
| X-Tt-Logid | 服务端返回的 logid，建议用户获取和打印方便定位问题 | 20250506234111719BC62BBA7C4C0C635A |

<span id="f2fccd99"></span>

## 2.2 WebSocket二进制协议

豆包端到端实时语音大模型API使用二进制协议传输数据，协议由4字节的header、optioanl、payload size和payload三部分组成，其中：

* header用于描述消息类型、序列化方式以及压缩格式等信息
* optional可选字段
    * sequence字段
    * event字段，用于描述链接过程中状态管理的预定义事件
    * connect id size/ connect id字段，用于描述连接类事件的标识
    * session id size/ session id 字段，用于描述会话类事件的标识
    * error code: 仅用于错误数据包，描述错误信息
* payload size代表payload的长度
* payload是具体负载的内容，依据不同的消息类型装载不同的内容

<span id="c403f206"></span>

### 二进制数据

<table>
<thead>
<tr>
<th>Byte</th>
<th>Left-4bit</th>
<th>Right-4bit</th>
<th>说明</th>
</tr>
</thead>
<tbody>
<tr>
<td rowspan="2">0</td>
<td>Protocol Version</td>
<td></td>
<td>目前只有v1，固定0b0001</td>
</tr>
<tr>
<td></td>
<td>Header Size</td>
<td>目前只有4字节固定0b0001</td>
</tr>
<tr>
<td>1</td>
<td>Message Type</td>
<td>Message type specific flags</td>
<td>详细见下面消息说明</td>
</tr>
<tr>
<td rowspan="2">2</td>
<td>Serialization method</td>
<td></td>
<td>
<ul>
<li>0b0000：Raw（无特殊序列化，主要针对二进制音频数据）</li>
<li>0b0001：JSON（主要针对文本类型消息）</li>
</ul>
</td>
</tr>
<tr>
<td></td>
<td>Compression method</td>
<td>
<ul>
<li>0b0000：无压缩【<strong>推荐</strong>】</li>
<li>0b0001：gzip</li>
</ul>
</td>
</tr>
<tr>
<td>3</td>
<td>0x00</td>
<td></td>
<td>Reserved</td>
</tr>
</tbody>
</table>

<span id="f3f2449c"></span>

#### Message Type

| Message Type | 含义 | 说明 |
|---|---|---|
| 0b0001 | Full-client request | 客户端发送文本事件的消息类型 |
| 0b1001 | Full-server response | 服务器返回的文本事件的消息类型 |
| 0b0010 | Audio-only request | 客户端发送音频数据的消息类型 |
| 0b1011 | Audio-only response | 服务器返回音频数据的消息类型 |
| 0b1111 | Error information | 服务器返回的错误事件的消息类型 |

<span id="a1bdc86f"></span>

### Message type specific flags

Optional可选字段code、sequence、event取决于Message type specific flags，而connect id和session id取决于事件类型。如果设置对应flag请**按照表格顺序**进行二进制组装。目前支持的全集如下所示：

<table>
<thead>
<tr>
<th>字段</th>
<th>长度（Byte）</th>
<th>说明</th>
<th>Message type specific flags</th>
</tr>
</thead>
<tbody>
<tr>
<td>code</td>
<td>4</td>
<td>【可选】错误码code</td>
<td>0b1111：错误数据包</td>
</tr>
<tr>
<td>sequence</td>
<td>4</td>
<td>【可选】描述客户端的事件序号</td>
<td>
<ul>
<li>0b0000：没有sequence字段</li>
<li>0b0001：序号大于 0 的非终端数据包</li>
<li>0b0010：最后一个无序号的数据包</li>
<li>0b0011：最后一个序号小于 0 的数据包，一般用-1表示</li>
</ul>
</td>
</tr>
<tr>
<td>event</td>
<td>4</td>
<td>【必须】描述连接过程中状态管理的预定义事件，详细参考<a href="https://bytedance.larkoffice.com/docx/JwKydEGDkojKxHxOrzNcYeewnyd#share-NceddeBUkot54QxBOemcYsKknFe">实时对话事件</a>中的事件ID</td>
<td>0b0100：携带事件ID</td>
</tr>
<tr>
<td>connect id size</td>
<td>4</td>
<td>【可选】客户事件携带的connect id对应的长度，只有Connect事件才能携带此字段</td>
<td>——</td>
</tr>
<tr>
<td>connect id</td>
<td>取决于connect id size</td>
<td>【可选】客户生成的connect id</td>
<td></td>
</tr>
<tr>
<td>session id size</td>
<td>4</td>
<td>【必须】客户事件携带的session id对应的长度，只有Session级别的事件携带此字段</td>
<td></td>
</tr>
<tr>
<td>session id</td>
<td>取决于session id size</td>
<td>【必须】客户事件携带的session id</td>
<td></td>
</tr>
</tbody>
</table>

<span id="de147d4f"></span>

### 具体的payload size和payload

payload可以放音频二进制数据，也可以放类似StartSession事件中的json数据。

| 字段 | 长度（Byte） | 说明 |
|---|---|---|
| payload size | 4 | payload长度 |
| payload | 长度取决于payload size | payload内容，可以是二进制音频数据，也可以是json字符串 |

<span id="bb30c6d3"></span>

#### 错误帧payload

```json
{
    "error": {{STRING}}
}
```

<span id="a5b00b9a"></span>

## 2.3 实时对话事件

通过WebSocket连接到豆包端到端实时语音大模型API之后，可以调用`S2S模型`进行语音到语音的对话。需要**发送客户端事件**来启动操作，并**监听服务器事件**以采取对应的操作。

<span id="4738c2ba"></span>

### 客户端事件

<table>
<thead>
<tr>
<th>事件ID</th>
<th>事件定义</th>
<th>事件类型</th>
<th>说明</th>
<th>示例</th>
</tr>
</thead>
<tbody>
<tr>
<td>1</td>
<td>StartConnection</td>
<td rowspan="2">Connect类事件</td>
<td>Websocket 阶段声明创建连接</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
<tr>
<td>2</td>
<td>FinishConnection</td>
<td>断开websocket连接，后面需要重新发起websocket连接</td>
<td></td>
</tr>
<tr>
<td>100</td>
<td>StartSession</td>
<td rowspan="10">Session类事件</td>
<td>
<p>asr字段用于描述识别阶段的相关配置：</p>
<ul>
<li>end_smooth_window_ms字段用于客户调整判断用户停止说话的时间，默认1500ms，取值范围[500ms, 50s]</li>
<li>enable_custom_vad字段用于标识是否开启自定义判断用户说话停止的参数，true代表开启，默认为false</li>
<li>enable_asr_twopass字段用于标识是否开启非流式模型识别能力，true代表开启，默认为false</li>
<li>boosting_table_id：热词表 ID，非流式模型识别能力开启时生效</li>
<li>boosting_table_name：热词表名称，非流式模型识别能力开启时生效</li>
<li>regex_correct_table_id：正则替换词表 ID，传值即生效</li>
<li>regex_correct_table_name：正则替换词表名称，传值即生效</li>
<li>context.hotwords：数组格式自定义热词 <code>[{"word":"xxx"}]</code>，非流式模型识别能力开启时生效</li>
<li>context.correct_words：map 格式文本替换规则 <code>{"正则原文本":"替换后"}</code>，传值即生效</li>
</ul>
<blockquote>补充：词表配置与 context 内配置同时传值时自动 merge 合并，所有规则叠加生效</blockquote>
<hr>
<p>dialog字段用于描述对话相关配置：</p>
<ul>
<li>bot_name字段用于修改基础人设信息，例如人名、来源等，默认为豆包，只针对<strong>O版本</strong>生效</li>
<li>system_role字段用于配置背景人设信息，描述角色的来源、设定等，例如"你是大灰狼、用户是小红帽，用户逃跑时你会威胁吃掉他。"，只针对<strong>O版本</strong>生效</li>
<li>speaking_style字段用于配置模型对话风格，例如"你说话偏向林黛玉。"、"你口吻拽拽的。"等，只针对<strong>O版本</strong>生效</li>
<li>长度限制：bot_name 最长不超过 20 个字符</li>
<li>dialog_id字段用于加载相同dialog id的对话记录，进而提升模型上下文记忆能力，目前服务端仅支持最近20轮QA对</li>
<li>character_manifest字段用于填充模型所扮演角色的描述信息，只针对<strong>SC版本</strong>生效</li>
<li>location字段用于客户端传入用户位置信息，以提升联网搜索结果的精准度，关闭内置联网时候无需此字段
    <ul>
    <li>country：默认中国</li>
    <li>country_code：默认CN</li>
    </ul>
</li>
<li>strict_audit字段用于声明安全审核等级，true代表严格审核、false代表普通审核，默认为true</li>
<li>dialog_context字段用于初始化上下文，需要按照user,assistant的qa对顺序进行传入，数组长度必须为偶数；如果timestamp为空的话，则会补充当前时间</li>
<li>audit_response字段用于指定用户query命中安全审核之后的自定义回复话术</li>
<li>enable_volc_websearch字段用于开关内置联网功能，开启内置联网参考火山引擎控制台<a href="https://www.volcengine.com/docs/85508/1650263">融合信息搜索API</a></li>
<li>volc_websearch_type字段用于指定搜索服务类型
    <ul>
    <li>web代表普通版，不传此参数默认为普通版</li>
    <li>web_summary代表总结版，需要客户指定才能生效</li>
    <li>web_agent代表搜索Agent，用于提升搜索质量，适用2.0版本</li>
    </ul>
</li>
<li>volc_websearch_api_key字段用于指定客户开通的融合信息搜索API或者搜索Agent服务访问密钥</li>
<li>volc_websearch_bot_id字段用于访问对应的搜索Agent服务</li>
<li>volc_websearch_result_count字段用于指定搜索结果条数，最多10条，默认10条</li>
<li>volc_websearch_no_result_message字段用于指定没有搜索结果时候的回复话术</li>
<li>input_mod使用text(纯文本)或者audio_file(录音文件)模式时，服务端会自动补充静音数据保证输入效果对齐麦克风模式，新增麦克风静音和按键两种模式</li>
<li>enable_music字段用于开关唱歌能力，打开唱歌开关之后会检索曲库唱歌数据送给模型提升模型唱歌能力，<code>适用版本1.2.1.1</code></li>
<li>enable_loudness_norm字段用于配置2.0版本输出音频响度均衡能力，true代表打开，false代表关闭，默认为false</li>
<li>enable_conversation_truncate字段用于配置2.0版本截断上下文功能的开启</li>
<li>enable_user_query_exit字段用于打开识别用户退出意图的开关，默认为false；打开此开关会在<code>TTSEnded</code>事件中增加一个信号用于客户端实现真实退出动作</li>
<li>【<strong>必传参数</strong>】model字段用于区分端到端模型版本，取值字段枚举：【1.2.1.1、2.2.0.0】
    <ul>
    <li><strong>1.2.1.1</strong>对应O2.0版本（规范版本号）</li>
    <li><strong>2.2.0.0</strong>对应SC2.0版本（规范版本号）</li>
    </ul>
</li>
</ul>
<hr>
<p>tts字段用于描述合成音频相关配置：</p>
<ul>
<li>explicit_dialect指定方言参数，<strong>当前仅在 2.0 模型 vv 音色生效</strong>，支持取值：<code>dongbei</code>、<code>sichuan</code>、<code>shaanxi</code>。</li>
<li>aigc_metadata字段用于AIGC 内容溯源与版权元信息，配合隐式水印使用，当前仅支持2.0版本模型</li>
<li>speech_rate字段用于控制输出语音播放的语速快慢，数值越大语速越快，数值越小语速越慢，取值范围[-50,100]，默认为0，当前仅支持2.0版本模型</li>
<li>loudness_rate字段用于控制输出语音音量，取值范围[-50,100]，默认为0，当前仅支持2.0版本模型</li>
<li>tts_2.0_model字段用于传递复刻音色效果，高表现力版本复刻音色固定传 <code>expressive</code>，当前仅支持O2.0版本模型</li>
</ul>
</td>
<td>
<p>asr配置示例：</p>
<pre><code class="language-json">{
    "asr": {
        "extra": {
            "end_smooth_window_ms": {{INT}},
            "enable_custom_vad": {{BOOLEAN}},
            "enable_asr_twopass": {{BOOLEAN}},
            "boosting_table_id": {{STRING}},
            "boosting_table_name": {{STRING}},
            "regex_correct_table_id": {{STRING}},
            "regex_correct_table_name": {{STRING}},
            "context": {
                "hotwords": [
                    {"word": {{STRING}}}
                ],
                "correct_words": map[string]string{}
            }
        }
    }
}</code></pre>
<p>dialog配置示例：</p>
<pre><code class="language-json">{
    "dialog": {
        "bot_name": {{STRING}},
        "system_role": {{STRING}},
        "speaking_style": {{STRING}},
        "dialog_id": {{STRING}},
        "character_manifest": {{STRING}},
        "location": {
            "longitude": {{Float64}},
            "latitude": {{Float64}},
            "city": {{STRING}},
            "country": {{STRING}},
            "province": {{STRING}},
            "district": {{STRING}},
            "town": {{STRING}},
            "country_code": {{STRING}},
            "address": {{STRING}}
        },
        "dialog_context": [
            {
                "role": {{STRING}},
                "text": {{STRING}},
                "timestamp": {{INT}}
            }
        ],
        "extra": {
            "strict_audit": {{BOOLEAN}},
            "audit_response": {{STRING}},
            "enable_volc_websearch": {{BOOLEAN}},
            "volc_websearch_type": {{STRING}},
            "volc_websearch_api_key": {{STRING}},
            "volc_websearch_result_count": {{INT}},
            "volc_websearch_no_result_message": {{STRING}},
            "input_mod": {{STRING}},
            "enable_music": {{BOOL}},
            "enable_loudness_norm": {{BOOL}},
            "enable_conversation_truncate": {{BOOL}},
            "enable_user_query_exit": {{BOOL}},
            "model": {{STRING}}
        }
    }
}</code></pre>
<p>tts配置示例：</p>
<pre><code class="language-json">{
    "tts": {
        "extra": {
            "explicit_dialect": {{STRING}},
            "aigc_metadata": {
                "enable": {{BOOL}},
                "content_producer": {{STRING}},
                "produce_id": {{STRING}},
                "content_propagator": {{STRING}},
                "propagate_id": {{STRING}}
            },
            "tts_2.0_model": {{STRING}}
        },
        "audio_config": {
            "speech_rate": {{INT}},
            "loudness_rate": {{INT}}
        }
    }
}</code></pre>
</td>
</tr>
<tr>
<td>102</td>
<td>FinishSession</td>
<td>客户端声明结束会话，后面可以复用websocket连接</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
<tr>
<td>200</td>
<td>TaskRequest</td>
<td>客户端上传音频</td>
<td>音频二进制数据</td>
</tr>
<tr>
<td>201</td>
<td>UpdateConfig</td>
<td>
客户端更新通话过程中的SP相关配置，其中dialog_id字段代表上下文唯一标识<br><br>
<strong>注意</strong>：右侧涉及配置字段均采用全量覆盖模式，请确保请求中包含完整字段信息
</td>
<td><pre><code class="language-json">{
    "tts": {
        "speaker": {{STRING}},
        "audio_config": {
            "speech_rate": {{INT}},
            "loudness_rate": {{INT}}
        }
    },
    "dialog": {
        "bot_name": {{STRING}},
        "system_role": {{STRING}},
        "speaking_style": {{STRING}},
        "dialog_id": {{STRING}},
        "location": {
            "longitude": {{Float64}},
            "latitude": {{Float64}},
            "city": {{STRING}},
            "country": {{STRING}},
            "province": {{STRING}},
            "district": {{STRING}},
            "town": {{STRING}},
            "country_code": {{STRING}},
            "address": {{STRING}}
        }
    }
}</code></pre></td>
</tr>
<tr>
<td>300</td>
<td>SayHello</td>
<td>客户端提交打招呼文本</td>
<td><pre><code class="language-json">{
    "content": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>400</td>
<td>EndASR</td>
<td>客户端在麦克风按键输入模式下即<strong>push_to_talk</strong>模式，需要在音频输入结束时向服务端发送音频结束信号</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
<tr>
<td>500</td>
<td>ChatTTSText</td>
<td>用户query之后，模型会生成闲聊结果。如果客户判断用户query不需要闲聊结果，可以指定文本合成音频</td>
<td><pre><code class="language-json">{
    "start": {{BOOLEAN}},
    "content": {{STRING}},
    "end": {{BOOLEAN}}
}</code></pre></td>
</tr>
<tr>
<td>501</td>
<td>ChatTextQuery</td>
<td>用户输入文本query，模型输出闲聊结果。若用户判断不采用音频输入进行query，可使用该事件输入文本进行query</td>
<td><pre><code class="language-json">{
    "content": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>502</td>
<td>ChatRAGText</td>
<td>用户query之后，模型会生成闲聊结果。如果客户判断用户query不需要闲聊结果，可以输入外部RAG知识，通过模型的总结和口语化改写之后输出对应音频。外部RAG输入整体长度不超过4K个字符。</td>
<td><pre><code class="language-json">{
    "external_rag": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>510</td>
<td>ConversationCreate</td>
<td rowspan="5">上下文管理事件</td>
<td>
上下文追加规则：
<ul>
<li>每次允许提交20轮(40条)问答（QA）记录</li>
<li>必须要上传完整问答（QA）对</li>
<li>若未提供时间戳，则将该记录追加至当前上下文末尾</li>
<li>若提供时间戳，则按时间顺序将该记录插入到上下文中</li>
<li>每条记录的时间戳要求严格递增；时间戳不能超过当前时间</li>
<li>时间戳策略需保持一致：要么所有记录均携带时间戳，要么全部不携带，不能混用</li>
</ul>
</td>
<td><pre><code class="language-json">{
    "items": [
        {
            "role": {{STRING}},
            "text": {{STRING}},
            "timestamp": {{INT}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>511</td>
<td>ConversationUpdate</td>
<td>
更新上下文规则（用于更新指定 item_id 对应消息的文本内容）：
<ul>
<li>item_id 可从是question_id即更新用户问题，也可以是reply_id即更新模型回复内容</li>
<li>question_id表示当前轮次中用户query的item_id，在一轮对话中不会变化</li>
<li>reply_id：表示当前轮次中模型回复消息的item_id</li>
</ul>
</td>
<td><pre><code class="language-json">{
    "items": [
        {
            "item_id": {{STRING}},
            "text": {{STRING}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>512</td>
<td>ConversationRetrieve</td>
<td>
查询上下文规则：
<ul>
<li>未传入item_id返回最近20轮完整对话上下文</li>
<li>传入item_id返回指定item_id所在轮次的上下文记录</li>
</ul>
</td>
<td><pre><code class="language-json">{
    "items": [
        {
            "item_id": {{STRING}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>513</td>
<td>ConversationTruncate</td>
<td>
截取上下文规则：
<ul>
<li>仅适用于2.0模型</li>
<li>dialog.extra的enable_conversation_truncate必须为true</li>
<li>item_id和audio_end_ms必传</li>
<li>仅保留对应item_id的<code>audio_end_ms</code>已播报毫秒时长对应的上下文内容</li>
</ul>
</td>
<td><pre><code class="language-json">{
    "item_id": {{STRING}},
    "audio_end_ms": {{INT}}
}</code></pre></td>
</tr>
<tr>
<td>514</td>
<td>ConversationDelete</td>
<td>
删除上下文规则：
<ul>
<li>删除操作以对话轮为单位进行</li>
<li>当传入某条 用户侧的 item_id 时，将同时删除与之成对的 助手回复记录（即整轮对话一起删除）</li>
<li>同理，若传入助手侧 item_id，系统也会删除与其对应的用户消息，确保上下文不出现不完整对话</li>
</ul>
</td>
<td><pre><code class="language-json">{
    "items": [
        {
            "item_id": {{STRING}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>515</td>
<td>ClientInterrupt</td>
<td></td>
<td>在麦克风按键输入模式下即<strong>push_to_talk</strong>模式，用于客户端打断服务端响应，便于进行下一次识别处理</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
</tbody>
</table>

备注：

* Websocket阶段：在 HTTP 建立连接之后Upgrade
* 客户端在发送FinishSession事件之后，websocket连接不会断开，客户端可以继续复用，复用时候需要再发送一次StartSession事件，即重新初始化会话
* Message Type = 0b0001，Message type specific flags = 0b0100，StartConnection事件二进制帧对应的字节数组示例：
    * [17 20 16 0 0 0 0 1 0 0 0 2 123 125]
* Message Type = 0b0001，Message type specific flags = 0b0100，SessionID = 75a6126e-427f-49a1-a2c1-621143cb9db3，jsonPayload = {"dialog":{"bot_name":"豆包","dialog_id":"","extra":null}}，StartSession事件二进制帧对应的字节数组示例：

```
[17 20 16 0 0 0 0 100 0 0 0 36 55 53 97 54 49 50 54 101 45 52 50 55 102 45 52 57 97 49 45 97 50 99 49 45 54 50 49 49 52 51 99 98 57 100 98 51 0 0 0 60 123 34 100 105 97 108 111 103 34 58 123 34 98 111 116 95 110 97 109 101 34 58 34 232 177 134 229 140 133 34 44 34 100 105 97 108 111 103 95 105 100 34 58 34 34 44 34 101 120 116 114 97 34 58 110 117 108 108 125 125]
```

* ChatTTSText事件请求示例：
    * 第一包json示例

```json
{
    "start": true,
    "content": "今天是",
    "end": false
}
```

* 中间包，用于流式上传待合成音频的文本

```json
{
    "start": false,
    "content": "星期二。",
    "end": false
}
```

* 最后一包，若用户在音频播报过程中发起新的 query 导致中断，且合成音频的 end 包尚未发送，此时无需再下发该 end 包，以避免多余流程或状态异常。

```json
{
    "start": false,
    "content": "",
    "end": true
}
```

* ChatRAGText事件请求中的external_rag是一个json数组字符串，对应的json描述：

```json
{
    "title": {{STRING}},
    "content": {{STRING}}
}
```

<span id="f83c6b99"></span>

### 服务端事件

<table>
<thead>
<tr>
<th>事件ID</th>
<th>事件定义</th>
<th>事件类型</th>
<th>说明</th>
<th>示例</th>
</tr>
</thead>
<tbody>
<tr>
<td>50</td>
<td>ConnectionStarted</td>
<td rowspan="3">Connect类</td>
<td>成功建立连接</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
<tr>
<td>51</td>
<td>ConnectionFailed</td>
<td>建立连接失败</td>
<td><pre><code class="language-json">{
    "error": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>52</td>
<td>ConnectionFinished</td>
<td>连接结束</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
<tr>
<td>150</td>
<td>SessionStarted</td>
<td rowspan="4">Session类</td>
<td>成功启动会话，返回的dialog id用于接续最近的对话内容，增加模型智能度</td>
<td><pre><code class="language-json">{
    "dialog_id": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>152</td>
<td>SessionFinished</td>
<td>会话已结束</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
<tr>
<td>153</td>
<td>SessionFailed</td>
<td>会话失败</td>
<td><pre><code class="language-json">{
    "error": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>154</td>
<td>UsageResponse</td>
<td>每一轮交互对应的用量信息</td>
<td><pre><code class="language-json">{
    "usage": {
        "input_text_tokens": {{INT}},
        "input_audio_tokens": {{INT}},
        "cached_text_tokens": {{INT}},
        "cached_audio_tokens": {{INT}},
        "output_text_tokens": {{INT}},
        "output_audio_tokens": {{INT}}
    }
}</code></pre></td>
</tr>
<tr>
<td>251</td>
<td>ConfigUpdated</td>
<td></td>
<td>UpdateConfig请求对应的ack</td>
<td><pre><code>{}</code></pre></td>
</tr>
<tr>
<td>350</td>
<td>TTSSentenceStart</td>
<td rowspan="4"></td>
<td>
合成音频的起始事件，tts_type取值类型有：
<ul>
<li>audit_content_risky（命中安全审核音频）</li>
<li>chat_tts_text（客户文本合成音频）</li>
<li>network（内置联网音频）</li>
<li>external_rag（外部RAG总结音频）</li>
<li>sing（唱歌音频）</li>
<li>default（闲聊音频）</li>
</ul>
</td>
<td><pre><code class="language-json">{
    "tts_type": {{STRING}},
    "text": {{STRING}},
    "question_id": {{STRING}},
    "reply_id": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>351</td>
<td>TTSSentenceEnd</td>
<td>合成音频的分句结束事件</td>
<td><pre><code class="language-json">{
    "question_id": {{STRING}},
    "reply_id": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>352</td>
<td>TTSResponse</td>
<td>返回模型生成的音频数据</td>
<td>payload装载二进制音频数据</td>
</tr>
<tr>
<td>359</td>
<td>TTSEnded</td>
<td>模型一轮音频合成结束事件，其中<code>status_code="20000002"</code>代表火山语音模型识别到用户的退出意图</td>
<td><pre><code class="language-json">{
    "question_id": {{STRING}},
    "reply_id": {{STRING}},
    "status_code": "20000002"
}</code></pre></td>
</tr>
<tr>
<td>450</td>
<td>ASRInfo</td>
<td rowspan="3"></td>
<td>模型识别出音频流中的首字返回的事件，用于打断客户端的播报</td>
<td><pre><code class="language-json">{
    "question_id": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>451</td>
<td>ASRResponse</td>
<td>模型识别出用户说话的文本内容</td>
<td><pre><code class="language-json">{
    "results": [
        {
            "text": {{STRING}},
            "is_interim": {{BOOLEAN}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>459</td>
<td>ASREnded</td>
<td>模型认为用户说话结束的事件</td>
<td><pre><code class="language-json">{}</code></pre></td>
</tr>
<tr>
<td>550</td>
<td>ChatResponse</td>
<td rowspan="3"></td>
<td>模型回复的文本内容</td>
<td><pre><code class="language-json">{
    "content": {{STRING}},
    "question_id": {{STRING}},
    "reply_id": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>553</td>
<td>ChatTextQueryConfirmed</td>
<td>ChatTextQuery请求对应的ack</td>
<td><pre><code class="language-json">{
    "question_id": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>559</td>
<td>ChatEnded</td>
<td>模型回复文本结束事件</td>
<td><pre><code class="language-json">{
    "question_id": {{STRING}},
    "reply_id": {{STRING}}
}</code></pre></td>
</tr>
<tr>
<td>567</td>
<td>ConversationCreated</td>
<td rowspan="5">上下文管理</td>
<td>增加上下文请求对应的ack，返回创建成功的上下文item数组</td>
<td><pre><code class="language-json">{
    "items": [
        {
            "item_id": {{STRING}},
            "role": {{STRING}},
            "text": {{STRING}},
            "timestamp": {{INT}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>568</td>
<td>ConversationUpdated</td>
<td>更新上下文请求对应的ack，更新成功返回 <code>{}</code>，更新失败返回错误提示</td>
<td><pre><code class="language-json">{
    "message": "the following item ids are missing: 1,2,3"
}</code></pre></td>
</tr>
<tr>
<td>569</td>
<td>ConversationRetrieved</td>
<td>查询上下文请求对应的ack</td>
<td><pre><code class="language-json">{
    "items": [
        {
            "item_id": {{STRING}},
            "role": {{STRING}},
            "text": {{STRING}},
            "timestamp": {{INT}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>570</td>
<td>ConversationTruncated</td>
<td>截断上下文请求对应的ack</td>
<td></td>
</tr>
<tr>
<td>571</td>
<td>ConversationDeleted</td>
<td>
删除上下文请求对应的ack，会把被删除的上下文返回。如果没有被删除的上下文，则会返回：
<pre><code class="language-json">{
    "status_code": 40000010,
    "message": "empty conversation deleted messages"
}</code></pre>
</td>
<td><pre><code class="language-json">{
    "items": [
        {
            "item_id": {{STRING}},
            "role": {{STRING}},
            "text": {{STRING}},
            "timestamp": {{INT}}
        }
    ]
}</code></pre></td>
</tr>
<tr>
<td>599</td>
<td>DialogCommonError</td>
<td></td>
<td>实时通话过程中相关错误描述</td>
<td><pre><code class="language-json">{
    "status_code": {{STRING}},
    "message": {{STRING}}
}</code></pre></td>
</tr>
</tbody>
</table>

备注：

* 服务器事件中json payload可能会多返回一些字段，客户端无需关心
* Message type specific flags = 0b0100，session id = 3c791a7d-227a-4446-993b-24f9e302cc98，TTSResponse事件示例：
    * [17 180 0 0 0 0 1 96 0 0 0 36 51 99 55 57 49 97 55 100 45 50 50 55 97 45 52 52 52 54 45 57 57 51 98 45 50 52 102 57 101 51 48 50 99 99 57 56 0 0 7 252 79 103 103 83 0 0 64 129 32 0 0 0 0 0 132 149 185 182 172 8 0 0 169 57 249 174 1 71 104 139 98 229 167 232 122 108 0 183 60 54 43 137 197 126 20 248 201 174]

<span id="23a2a7e8"></span>

# 3 快速开始

<span id="3aa250bf"></span>

## Python示例

<Attachment link="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/24c5221cb7b64875b0e5b317598fab92~tplv-goo7wpa0wc-image.image" name="realtime_dialog.zip" ></Attachment>

<span id="c8f1b1ef"></span>

## Go示例

<Attachment link="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/a18bd14b9e22455eb7a21d34c842de02~tplv-goo7wpa0wc-image.image" name="realtime_dialog.zip" ></Attachment>

<span id="04afb752"></span>

## Java示例

<Attachment link="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/2cbd3ab7c62b45f884ef5f3c71849c04~tplv-goo7wpa0wc-image.image" name="realtime_dialog.zip" ></Attachment>

您可以通过以下步骤，快速体验与 Realtime 模型API实时对话的功能。

1. 下载realtime_dialog.zip文件到本地，依据操作系统类型对`gordonklaus/portaudio`依赖进行安装：
    1. macOS：

```bash
brew install portaudio
```

    2. CentOS：

```bash
sudo yum install -y portaudio portaudio-devel
```

    3. Debian/Ubuntu：

```bash
sudo apt-get install portaudio19-dev
```

2. 安装后在项目下运行：

```bash
# go执行命令
go run . -v=0

# python执行命令
python main.py
```

<span id="455d36b0"></span>

# 4 交互示例

RealtimeAPI的交互流程目前只支持server_vad模式，该模式的交互流程如下：

1. 客户端发送StartSession事件初始化会话
2. 客户端可以随时通过TaskRequest事件将音频发送到服务端
3. 服务端在检测到用户说话的时候，会返回ASRInfo和ASRResponse事件，同时在检测到用户说话结束之后返回ASREnded事件
4. 服务端合成的音频通过TTSResponse事件将音频返回给客户端

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/3722b9de766a484cb236ced79fa44eb7~tplv-goo7wpa0wc-image.image" width="400px" /></div>

<span id="a72c98bd"></span>

## 4.1 文本输入

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/f6f879039f39402a8d3ecf505bec2b46~tplv-goo7wpa0wc-image.image" width="400px" /></div>

<span id="28a074db"></span>

## 4.2 合成音频

当客户判定不使用模型生成闲聊内容时，系统允许客户多次上传文本执行音频合成，以满足多样化需求。整体交互示例如下所示：

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/389354b7d57d4f7793e41182397fa7eb~tplv-goo7wpa0wc-image.image" width="400px" /></div>

<span id="53076931"></span>

## 4.3 外部RAG输入

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/d57dfa283e774048b2d643d709f59d9d~tplv-goo7wpa0wc-image.image" width="400px" /></div>

<span id="f3332a8e"></span>

## 4.4 联网Agent搜索源

<div style="text-align: center"><img src="https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/42566f09cea94500850a5eb4a1f8f2cf~tplv-goo7wpa0wc-image.image" width="400px" /></div>

<span id="56a81be5"></span>

# 5 错误码

提示：客户端在遇到服务端 5xx 错误时，可以统一触发重连逻辑。

<table>
<thead>
<tr>
<th>错误码</th>
<th>错误信息关键字</th>
<th>错误描述</th>
</tr>
</thead>
<tbody>
<tr>
<td rowspan="5">42000020</td>
<td>StartSession event payload asr extra is null</td>
<td>客户端在发送StartSession事件时候，asr.extra置空引发此报错</td>
</tr>
<tr>
<td>StartSession event payload tts extra is null</td>
<td>客户端在发送StartSession事件时候，tts.extra置空导致此报错</td>
</tr>
<tr>
<td>dialog.extra.model= ? cant support enable_music=true</td>
<td>enable_music字段只<code>适用版本1.2.1.1</code>，客户端在发送StartSession事件时候使用了不支持唱歌的版本</td>
</tr>
<tr>
<td>volc_websearch_bot_id is required</td>
<td>使用web_agent联网模式时，没有传递volc_websearch_bot_id</td>
</tr>
<tr>
<td>volc_websearch_api_key is required</td>
<td>使用web，web_summary，web_agent联网模式时，没有传递volc_websearch_api_key</td>
</tr>
<tr>
<td>45000003</td>
<td>Abnormal silence audio</td>
<td>超过10分钟没有对话交互，服务端释放链接</td>
</tr>
<tr>
<td rowspan="2">50000000</td>
<td>AudioQueryError</td>
<td>模型闲聊过程中推理出错</td>
</tr>
<tr>
<td>Yaml: line 43: found unknown escape character</td>
<td>通常是speaking style和system role里面包含非法字符，建议检查一下客户端上传的prompt配置</td>
</tr>
<tr>
<td rowspan="4">55000001</td>
<td>ServerError</td>
<td>模型闲聊过程中推理出错</td>
</tr>
<tr>
<td>ContextCanceled</td>
<td>客户端没有正常发送FinishSession结束链接，强烈推荐发送完<strong>FinishSession</strong>事件收到回复之后再断开ws链接</td>
</tr>
<tr>
<td>ClientError:InvalidSpeaker</td>
<td>端到端链路不同音色适用不同版本，可以再通过官方文档对比检查下model参数和音色参数是否匹配</td>
</tr>
<tr>
<td>ExceededConcurrentDurationLimit</td>
<td>模型闲聊过程中推理出错</td>
</tr>
<tr>
<td>52000042</td>
<td>DialogAudioIdleTimeoutError</td>
<td>客户端在发送音频时候，补充静音出错，推荐dialog.extra.input_mod设置为<strong><code>keep_alive</code></strong>即可解决此问题</td>
</tr>
<tr>
<td>50700000</td>
<td>CallWithTimeout: stream recv timeout</td>
<td>模型闲聊过程中推理出错</td>
</tr>
<tr>
<td>50000000</td>
<td>ServerError:BigASRFailedCode:1022</td>
<td>模型闲聊过程中推理出错</td>
</tr>
<tr>
<td>52000022</td>
<td>AudioChatError</td>
<td>模型闲聊过程中推理出错</td>
</tr>
<tr>
<td>52000035</td>
<td>S2SQueryConnectError</td>
<td>模型闲聊过程中推理出错</td>
</tr>
<tr>
<td>52000016</td>
<td>AudioTTSIdleTimeoutError</td>
<td>模型音频合成过程中超时报错</td>
</tr>
<tr>
<td>52000011</td>
<td>AudioChatRecvTimeoutError</td>
<td>模型闲聊过程中推理文本返回超时</td>
</tr>
</tbody>
</table>

<span id="b4feaae9"></span>

# 6 文档修订记录

| 日期 | 更新内容 |
|---|---|
| 26.04.29 | 文档整体优化 |
| 26.03.07 | O2.0 小版本迭代升级；O2.0版本支持复刻音色；支持用户query退出机制，便于用户表达退出意图时候能够让客户端作出对应动作 |
| 26.02.26 | 支持基于客户端实际播报进度进行上下文对齐，仅向模型暴露已播放内容，避免模型感知完整生成文本，从而减少理解偏差与上下文污染 |
| 26.01.15 | 端到端API支持ASR识别链路热词和替换词配置 |
| 26.01.05 | 支持通话过程中更新SP相关配置 |
| 25.12.17 | O版本和SC版本升级到2.0版本，其中O2.0包含唱歌能力提升，SC2.0包含克隆音色以及角色扮演效果提升；支持客户端发送opus音频到实时通话API |
| 25.11.27 | 支持初始化上下文，以及上下文增删改查能力 |
| 25.11.24 | 提供java示例 |
| 25.10.28 | 服务端事件ASRInfo增加返回question_id字段；TTSSentenceStart事件增加返回question_id和reply_id字段；客户端增加麦克风静音模式保活机制；ChatTextQuery增加ack事件553 |
| 25.10.10 | 支持按需开启流式和非流式二遍识别模式，即在一次语音请求中先使用流式实时返回逐字文本，再使用非流式提升最终的识别准确率 |
| 25.09.23 | 放开和prompt相关的长度限制，丰富客户接入场景 |
| 25.09.22 | 支持自定义配置判断用户说话停止的参数；**s2s模型-SC版本**开放支持内置联网和外部RAG输入能力 |
| 25.09.11 | **s2s模型-O版本**支持外部RAG输入；客户在使用录音文件或者文本输入时候，客户端不需要补充发送静音，只需指定对应的模式参数即可，同时无需配置recv_timeout参数 |
| 25.09.09 | **s2s模型-SC版本**支持角色扮演、声音复刻能力；在使用此能力时候，需要传入对应的克隆音色以及角色描述，之前的bot_name、system_role、speaking_style参数不会生效 |
| 25.09.05 | 支持纯文本模式demo，t2s模式可以使用recv_timeout参数扩大超时时间避免还需要发送静音的问题 |
| 25.08.27 | 支持文本query和端到端模型进行交互，需要注意的是，再使用文本query进行交互时候，静音音频还是要发送的 |
| 25.08.20 | demo示例放开用户说话停止时间参数；system_role和speaking_style总长放开到4000 |
| 25.08.13 | Go demo修复并发写websocket的问题；支持内置联网开关，默认关闭；支持用户自己开通火山融合搜索服务；支持返回用量信息到客户端；支持system_role和speaking_style传入带转义字符的文本 |
| 25.08.06 | demo示例新增代码：支持传入录音文件；支持多音色；支持两种pcm位深 |
| 25.08.01 | 文档更新功能：支持两种pcm位深；支持多发音人；支持内置联网 |
| 25.07.14 | 支持客户自定义用户query命中安全审核时候的回复话术，新增audit_response字段 |
| 25.07.09 | go示例修复一个tts音色配置bug |
| 25.07.03 | python示例开放模型人设区域，提升端到端模型自定义能力；增加SayHello、ChatTTSText事件发送示例 |
| 25.07.01 | 客户端在发送ChatTTSText事件时候一定要在收到ASREnded事件之后；增加一些报错处理，例如appkey错误、sp配置长度超过限制 |
| 25.06.25 | Go示例开放模型人设区域，提升端到端模型自定义能力；增加SayHello、ChatTTSText事件发送示例 |
| 25.06.10 | 更新realtime_dialog示例，用户query打断本地播放音频 |
| 25.06.05 | 更新realtime_dialog 示例，ctrl+c之后发送FinishSession、FinishConnection事件之后，再调用close断开websocket连接 |
| 25.06.05 | 补充客户接入ChatTTSText的最佳实践 |
| 25.06.04 | 删除服务端返回的UsageResponse事件，客户可以在火山控制台查看用量 |
| 25.06.04 | 更新realtime_dialog Go示例demo，新增sayHello、chatTTSTesxt数据构造示例 |
| 25.06.03 | 新增realtime_dialog Python示例demo |
| 25.05.30 | 更新realtime_dialog示例，新增pcm保存到文件代码示例 |
| 25.05.30 | 更新Message type specific flags说明，注明必须传的字段 |
| 25.05.28 | 更新realtime_dialog Go示例demo，修复录音上传慢问题 |
