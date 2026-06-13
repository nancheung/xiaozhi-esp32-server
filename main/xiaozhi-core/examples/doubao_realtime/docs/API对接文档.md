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

见：[接口说明.md](%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E.md)

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

见：[错误码.md](%E9%94%99%E8%AF%AF%E7%A0%81.md)

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
