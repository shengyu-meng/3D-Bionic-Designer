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

workflow_file = os.path.abspath("./3D-Bionic-Product-Designer-V08_api.json")

    
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

def generate_design(creature_text, design_object, seed, input_image):
    """Main generation function with proper websocket handling"""
    try:
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

        if input_image is not None:
            image = Image.fromarray(input_image)
            image = image.resize((int(image.size[0] * (768 / min(image.size))), 
                               int(image.size[1] * (768 / min(image.size)))))
            image_path = os.path.join(input_dir, "input_image.jpg")
            image.save(image_path)
            prompt["63"]["inputs"]["image"] = image_path

        # Queue prompt and get prompt_id
        prompt_id = queue_prompt(prompt, client_id)['prompt_id']
        current_node = ""  # 当前节点的名称
        start_time = time.time()
        timeout = 300  # 5 minutes timeout
        
        while True:
            if time.time() - start_time > timeout:
                return "Operation timed out", "Operation timed out", None, None
                
            try:
                out = ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    
                    # Handle progress updates
                    if message['type'] == 'progress':
                        data = message['data']
                        print(f'Step: {data["value"]} of {data["max"]}')
                        
                    # Handle execution completion
                    elif message['type'] == 'executing':
                        data = message['data']
                        
                        # # wip
                        # if current_node == '303':  # 判断当前节点是否为保存图片的节点
                        #     images_output = output_images.get(current_node, [])  # 获取当前节点已保存的图片列表
                        #     # WebSocket传输的图片数据前8个字节是二进制消息头
                        #     # 前8个字节包含了消息类型和数据长度等元数据信息
                        #     # out[8:]表示跳过这8个字节的消息头，只获取实际的图片二进制数据
                        #     images_output.append(out[8:])  # 将接收到的图片数据(跳过8字节消息头)添加到列表中
                        #     output_images[current_node] = images_output  # 更新输出图片字典中的当前节点的图片列表
                                    
                        if data['node'] is None and data['prompt_id'] == prompt_id:
                            time.sleep(1)  # Wait for file writes to complete
                            
                            # Get outputs
                        
                            history = get_history(prompt_id)[prompt_id]
                            latest_image = history['outputs']['282']['files'][0]
                            text1 = history['outputs']['284']['text'][0]
                            text2 = history['outputs']['285']['text'][0]
                            latest_obj = history['outputs']['269']['text'][0]
                            if latest_obj:
                                try:
                                    latest_obj = mesh_convert(latest_obj)
                                except Exception as e:
                                    print(f"Error converting mesh: {e}")
                                    latest_obj = None
                            return text1, text2, latest_image, latest_obj

            except websocket.WebSocketException as e:
                print(f"WebSocket error: {e}")
                return "WebSocket error", "WebSocket error", None, None
                
    except Exception as e:
        print(f"Error: {e}")
        return f"Error: {str(e)}", "Error occurred", None, None
        
    finally:
        # Always close the websocket
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

with gr.Blocks() as demo:
    # gr.Markdown(HEADER)
    with gr.Row(variant="panel"):
        with gr.Column():
            creature_text = gr.Textbox(label="Reference Creature", lines=1)
            design_object = gr.Textbox(label="Design target object", lines=1)
            seed = gr.Slider(value=0, minimum=0, maximum=9999, step=1)
            submit = gr.Button("Generate", elem_id="generate", variant="primary")
        with gr.Column():
            input_image = gr.Image(label="Reference Image",height=300)
    with gr.Row(variant="panel"):
        output_text1 = gr.Textbox(label="Design hypothesis (integrates biological feacture with design objectives)", lines=8,interactive=False)
        output_text2 = gr.Textbox(label="Visual Description of Design", lines=8,interactive=False)
    with gr.Row(variant="panel"):
        output_image = gr.Image(label="Output Image", interactive=False)
        output_model = gr.Model3D(label="Output Model", interactive=False)
    submit.click(fn=generate_design, inputs=[creature_text, design_object, seed, input_image], \
                    outputs=[output_text1, output_text2, output_image, output_model])
# demo.queue(max_size=10)
# demo.launch()
demo.launch(server_name="0.0.0.0", server_port=7860, share=True, allowed_paths=[comfyui_output_path])