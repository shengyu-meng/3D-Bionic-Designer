import os
import time

import gradio as gr
import numpy as np

from PIL import Image

# import requests
import json
import uuid 
from PIL import Image
import websocket #NOTE: websocket-client (https://github.com/websocket-client/websocket-client)
import urllib.request
import urllib.parse

import pymeshlab

server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())
ws = websocket.WebSocket()
ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))

#保存上传图片的文件夹
input_dir = os.path.abspath("./temp/input_temp")
# 添加ComfyUI输出路径到允许路径列表
comfyui_output_path = "D:/01_DL/ComfyUI_windows_portable/ComfyUI/output"

workflow_file = os.path.abspath("./3D-Bionic-Product-Designer-V10_API.json")

    
def mesh_convert(input_file, output_file=None):
    # Load the mesh from an OBJ file
    if output_file is None:
        output_file = input_file
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(input_file)
    # Save the mesh to a new mesh
    ms.save_current_mesh(output_file, save_vertex_color=True)
    return output_file

def queue_prompt(prompt, client_id):
    """Queue a prompt to ComfyUI"""
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_history(prompt_id):
    # 发送HTTP请求获取指定prompt_id的历史记录
    with urllib.request.urlopen("http://{}/history/{}".format(server_address, prompt_id)) as response:
        return json.loads(response.read())

def generate_design(creature_text, design_object, seed, randomize_seed, input_image, gen_language):
    """Main generation function with proper websocket handling"""
    try:
        # 如果启用随机种子，则生成一个随机数
        if randomize_seed:
            seed = np.random.randint(0, 9999)
            
        # 在开始时显示加载提示
        yield "Generating...", "Generating...", None, None, gr.update(value=seed)
        
        # Create new websocket connection for each request
        client_id = str(uuid.uuid4())
        ws = websocket.WebSocket()
        ws.connect(f"ws://{server_address}/ws?clientId={client_id}")

        # Load and modify workflow
        with open(workflow_file, 'r', encoding='utf-8') as file:
            prompt = json.load(file)

        if creature_text is not None:
            prompt["65"]["inputs"]["text"] = f"Now, your reference creature is {creature_text}."
            prompt["206"]["inputs"]["seed"] = seed

        if design_object is not None:
            prompt["172"]["inputs"]["text"] = design_object
        
        if gen_language is not None:
            prompt["309"]["inputs"]["text"] = gen_language

        if input_image is not None:
            try:
                # 确保输入图像是有效的
                if isinstance(input_image, np.ndarray):
                    image = Image.fromarray(input_image)
                elif isinstance(input_image, str):
                    image = Image.open(input_image)
                else:
                    raise ValueError("Invalid input image format")

                # 验图像模式
                if image.mode not in ['RGB', 'RGBA']:
                    image = image.convert('RGB')

                # 限制图像最大尺寸
                max_size = 2048
                if max(image.size) > max_size:
                    ratio = max_size / max(image.size)
                    new_size = tuple(int(dim * ratio) for dim in image.size)
                    image = image.resize(new_size, Image.Resampling.LANCZOS)

                # 调整到目标尺寸
                target_size = (int(image.size[0] * (768 / min(image.size))), 
                             int(image.size[1] * (768 / min(image.size))))
                image = image.resize(target_size, Image.Resampling.LANCZOS)

                # 确保目录存在
                os.makedirs(input_dir, exist_ok=True)
                
                # 保存图像
                image_path = os.path.join(input_dir, f"input_image_{client_id}.jpg")
                image.save(image_path, 'JPEG', quality=95)
                prompt["63"]["inputs"]["image"] = image_path

            except Exception as e:
                print(f"Error processing input image: {e}")
                yield "Error processing input image", "Error occurred", None, None, gr.update(value=seed)
                return

        # Queue prompt and get prompt_id
        prompt_id = queue_prompt(prompt, client_id)['prompt_id']
        current_node = ""
        start_time = time.time()
        timeout = 300

        # 跟踪每个输出的状态
        text1_done = False
        text2_done = False
        image_done = False
        obj_done = False

        while True:
            if time.time() - start_time > timeout:
                return "Operation timed out", "Operation timed out", None, None, gr.update(value=seed)
                
            try:
                out = ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    # print(message)
                    
                    if message['type'] == 'executed':
                        data = message['data']
                        current_node = data['node']

                        if current_node == '315':  # 设计假设文本
                            try:               
                                text1 = message['data']['output']['text'][0]
                                text1_done = True
                                yield (text1, 
                                      "Generating..." if not text2_done else gr.update(), 
                                      None if not image_done else gr.update(), 
                                      None if not obj_done else gr.update(),
                                      gr.update(value=seed))
                            except Exception as e:
                                print(f"Error accessing output: {e}")
                                
                        elif current_node == '317':  # 视觉描述文本
                            try:               
                                text2 = message['data']['output']['text'][0]
                                text2_done = True
                                yield (text1 if text1_done else "Generating...", 
                                      text2,
                                      None if not image_done else gr.update(), 
                                      None if not obj_done else gr.update(),
                                      gr.update(value=seed))
                            except Exception as e:
                                print(f"Error accessing output: {e}")
                                
                        elif current_node == '282':  # 图片输出
                            try:               
                                latest_image = message['data']['output']['files'][0]
                                image_done = True
                                yield (text1 if text1_done else "Generating...", 
                                      text2 if text2_done else "Generating...",
                                      latest_image, 
                                      None if not obj_done else gr.update(),
                                      gr.update(value=seed))
                            except Exception as e:
                                print(f"Error accessing output: {e}")
                                
                        elif current_node == '269':  # 3D模型输出
                            try:               
                                latest_obj = message['data']['output']['text'][0]
                                if latest_obj:
                                    try:
                                        latest_obj = mesh_convert(latest_obj)
                                        obj_done = True
                                        yield (text1 if text1_done else "Generating...", 
                                              text2 if text2_done else "Generating...",
                                              latest_image if image_done else None, 
                                              latest_obj,
                                              gr.update(value=seed))
                                    except Exception as e:
                                        print(f"Error converting mesh: {e}")
                            except Exception as e:
                                print(f"Error accessing output: {e}")

                    # Handle execution completion
                    if message['type'] == 'executing':
                        data = message['data']
                        if data['node'] is None and data['prompt_id'] == prompt_id:
                            break

            except websocket.WebSocketException as e:
                print(f"WebSocket error: {e}")
                yield "WebSocket error", "WebSocket error", None, None, gr.update(value=seed)
                break
                
    except Exception as e:
        print(f"Error: {e}")
        yield f"Error: {str(e)}", "Error occurred", None, None, gr.update(value=seed)
        
    finally:
        try:
            ws.close()
        except:
            pass

# 在程序开始时添加

def ensure_directories():
    """Ensure all required directories exist"""
    directories = [input_dir]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)

# 在主程序开始时调用
ensure_directories()

with gr.Blocks(css="""
    .markdown-display { 
        height: 385px;
        overflow-y: auto;
        padding: 2px;
        border: 1px solid #ddd;
        border-radius: 2px;
    }
    .markdown-label {
        font-size: 1rem;
        font-weight: 500;
        margin-bottom: 0.2rem;
        color: var(--body-text-color);
    }
    /* 移除外层容器的滚动设置 */
    .markdown-column {
        height: auto !important;
    }
    /* 移除中间容器的滚动设置 */
    .markdown-column > div {
        height: auto !important;
        overflow: visible !important;
    }
    /* 确保内容容器正常显示 */
    .contain-content {
        height: auto !important;
    }
    /* Add styles for the examples container */
    .examples-container {
        height: 150px; /* 设置固定高度 */
        overflow-y: auto; /* 启用垂直动 */
    }
    /* 确保 Examples 组件填满容器高度 */
    .examples-container > div {
        height: 100%;
    }
""") as demo:
    # gr.Markdown(HEADER)
    with gr.Row(variant="panel"):
        # 侧列设置较小的scale值
        with gr.Column(scale=1):
            gr.HTML('<div style="margin-bottom:0.4em">Bio Image / バイオイメージ / 生物图像</div>')
            input_image = gr.Image(label="Bio Image", height=300)
            gr.HTML('<div style="margin-bottom:0.4em">Bio Reference / バイオリファレンス / 生物参考</div>')
            creature_text = gr.Textbox(label="Bio Reference", lines=1)
            gr.HTML('<div style="margin-bottom:0.4em">Design Target / デザイン対象 / 设计目标</div>')
            design_object = gr.Textbox(label="Design Target", lines=1)
            
            # Examples 部分移动到这里
            gr.HTML('<div style="margin-bottom:0.4em">Input Examples / サンプル入力 / 示例输入</div>')
            # Define examples dictionary first
            examples = {
                "None": [None, None, None],  # 添加 None 选项
                "Coral x Chair": ["coral", "chair", "./asset/coral.jpg"],
                "Mycelium x Pavillion": ["mycelium", "pavillion", "./asset/mycelium.jpg"], 
                "Coral x Table": ["coral", "table", "./asset/coral.jpg"],
                "Rose x Skirt": ["rose", "skirt", "./asset/rose.jpg"],
                "Butterfly x Aircraft": ["butterfly", "Aircraft", "./asset/butterfly.jpg"],
                "Fish x Boat": ["fish", "boat", "./asset/fish.jpg"],
                "Moss x Bed": ["moss", "bed", "./asset/moss.jpg"]
            }
            
            example_dropdown = gr.Dropdown(
                choices=list(examples.keys()),
                label=None,
                value="None"  # 设置默认值为 "None"
            )

            def load_example(choice):
                if choice == "None":
                    return [None, None, None]  # 清空所有输入
                return examples[choice]

            example_dropdown.change(
                fn=load_example,
                inputs=[example_dropdown],
                outputs=[creature_text, design_object, input_image]
            )

            # Seed 部分移到 Examples 后面
            gr.HTML('<div style="margin-bottom:0.4em">Seed</div>')
            with gr.Row():
                seed = gr.Slider(label=None, value=43, minimum=0, maximum=9999, step=1)
                randomize_seed = gr.Checkbox(label="Random", value=False)
                
            gr.HTML('<div style="margin-bottom:0.4em">Generation Language / 生成言語 / 生成文本语言</div>')
            gen_language = gr.Dropdown(
                choices=["English", "Japanese", "Chinese"],
                value="English",
                interactive=True,
                label=None
            )
            
            submit = gr.Button("Generate / 生成する / 生成", elem_id="generate", variant="primary")
            
        # 中间和右侧列设置较大的scale值
        with gr.Column(scale=3):
            # 添加英/日/中三语说明
            gr.HTML('''
                <div style="margin-bottom: 1em; font-size: 1.1rem; text-align: left;">
                    <p>3D Bionic Designer / 生物模倣型3D製品デザイナー / 3D仿生产品设计师</p>
                </div>
            ''')
            output_model = gr.Model3D(label="Output Model", interactive=False, height=550)
            # 减小 height 参数使图片显示区域变小
            output_image = gr.Image(label="Output Image", interactive=False, height=450)
        with gr.Column(scale=2, elem_classes=["markdown-column"]):
            with gr.Column(elem_classes=["contain-content"]):
                gr.HTML('''<div class="markdown-label" style="font-size: 0.85rem;">Design hypothesis<br>ザイン仮説<br>设计假设</div>''')
                output_text1 = gr.Markdown(elem_classes=["markdown-display"], height=400)
                gr.HTML('''<div class="markdown-label" style="font-size: 0.85rem;">Visual Description of Design<br>デザインの視覚的説明<br>设计视觉描述</div>''')
                output_text2 = gr.Markdown(elem_classes=["markdown-display"], height=400)
                gr.Markdown("""
                ### Links
                - GitHub: [3D-Bionic-Designer](https://github.com/shengyu-meng/3D-Bionic-Designer)
                - About me: [Shengyu Meng (Simon)](https://shengyu.me/en/me-en)
                """)
    submit.click(
        fn=generate_design,
        inputs=[creature_text, design_object, seed, randomize_seed, input_image, gen_language],
        outputs=[output_text1, output_text2, output_image, output_model, seed],
        api_name="generate"
    )
    


# 启动时启用队
demo.queue()
demo.launch(allowed_paths=[comfyui_output_path],share=True)