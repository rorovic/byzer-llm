from pyjava.udf import UDFMaster
from pyjava import PythonContext,RayContext
from typing import Dict,Any,List,Optional,Union
from pyjava.udf import UDFBuilder
import ray
from ray.util.client.common import ClientActorHandle, ClientObjectRef
import json
import dataclasses

# create a enum for the role
class Role:
    User = "user"
    Assistant = "assistant"
    System = "system"

@dataclasses.dataclass
class LLMHistoryItem:
      role: str
      content: str

@dataclasses.dataclass
class LLMResponse:
    output: str
    input: str

@dataclasses.dataclass
class LLMRequestExtra:
    system_msg:str = "You are a helpful assistant. Think it over and answer the user question correctly."
    user_role:str = "User"
    assistant_role:str = "Assistant"
    history:List[LLMHistoryItem] = dataclasses.field(default_factory=list)
    


@dataclasses.dataclass
class LLMRequest:
    instruction: Union[str,List[str]]
    embedding: bool = False
    max_length: int = 1024
    top_p: float = 0.7
    temperature: float = 0.9
    extra_params: LLMRequestExtra = LLMRequestExtra()

      
class ByzerLLM:
    def __init__(self,url:Optional[str]=None,**kwargs):
        self.url = url       
        self.sys_conf = {}
        
        self.sql_model = "context" in globals()

        if url is not None and self.sql_model:            
            v = globals()
            self.context = v["context"]
            self.ray_context = RayContext.connect(v, self.url, **kwargs)
        else:
            self.context = PythonContext(
                0,[],self.sys_conf
            ) 
            self.context.have_fetched = True
            self.ray_context = self.context.rayContext
    
    def setup(self,name:str, value:Any)->'ByzerLLM':
        self.sys_conf[name]=value
        # update the context conf
        self.context.conf = self.sys_conf
        return self

    def deploy(self,model_path:str,
               pretrained_model_type:str,
               udf_name:str,
               infer_params:Dict[str,Any]):        
        from byzerllm import common_init_model
        self.setup("UDF_CLIENT",udf_name)
        model_type = pretrained_model_type
        
        if pretrained_model_type.startswith("saas/"):
            model_type = pretrained_model_type.split("/")[-1]
            import importlib            
            infer_module = importlib.import_module(f'from byzerllm.saas.{model_type} import CustomSaasAPI')
            from byzerllm.utils.text_generator import simple_predict_func
            def init_model(model_refs: List[ClientObjectRef], conf: Dict[str, str]) -> Any:
                from byzerllm import consume_model
                consume_model(conf)                
                infer = infer_module(infer_params)
                return (infer,None)
            UDFBuilder.build(self.ray_context,init_model,simple_predict_func)
            return 


        if pretrained_model_type == "bark":
            from byzerllm.bark.bark_voice import build_void_infer, ZH_SPEAKER, EN_SPEAKER            
            def init_model(model_refs: List[ClientObjectRef], conf: Dict[str, str]) -> Any:
                infer = build_void_infer(
                model_dir=model_path,
                tokenizer_dir=f"{model_path}/pretrained_tokenizer")
                return infer
            def predict_func(model,v):
                data = [json.loads(item) for item in v]
                results=[{"predict":model.text_to_voice(item["instruction"]).tolist(),"labels":""} for item in data]
                return {"value":[json.dumps(results,ensure_ascii=False,indent=4)]}
            UDFBuilder.build(self.ray_context,init_model,predict_func)
            return                
        
        if pretrained_model_type.startswith("custom/"):
            model_type = pretrained_model_type.split("/")[-1]

        predict_func = "simple_predict_func"
        if model_type == "chatglm2":
            predict_func = "chatglm_predict_func"

        import importlib            
        infer_module = importlib.import_module(f'byzerllm.{model_type} as infer')
        predict_module = importlib.import_module(f"from byzerllm.utils.text_generator import {predict_func}")
        
        def init_model(model_refs: List[ClientObjectRef], conf: Dict[str, str]) -> Any:
            common_init_model(model_refs,conf,model_path, is_load_from_local=True)
            model = infer.init_model(model_path,infer_params,conf)
            return model
        
        UDFBuilder.build(self.ray_context,infer_module,predict_module)


    def emb(self, model, request:LLMRequest ,extract_params:Dict[str,Any]={})->List[List[float]]:
        if isinstance(request.instruction,str):
            v = [{
            "instruction":request.instruction,
            "embedding":True,
            "max_length":request.max_length,
            "top_p":request.top_p,
            "temperature":request.temperature,
            ** request.extra_params.__dict__,
            ** extract_params}] 
        else: 
            v = [{
            "instruction":x,
            "embedding":True,
            "max_length":request.max_length,
            "top_p":request.top_p,
            "temperature":request.temperature,
            ** request.extra_params.__dict__,
            ** extract_params} for x in request.instruction]    
        res = self._query(model,v) 
      
        return [LLMResponse(output=item["predict"],input=item["input"]) for item in res]
    
    def _generate_ins(self,ins:str,request:LLMRequest):
         if request.extra_params.user_role:
            return f'{request.extra_params.system_msg}\n\n{request.extra_params.user_role}:{ins}\n{request.extra_params.assistant_role}:'
         return ins

    def chat(self,model,request:LLMRequest,extract_params:Dict[str,Any]={})->List[LLMResponse]:


        if isinstance(request.instruction,str):
            v = [{
            "instruction":self._generate_ins(request.instruction,request),
            "max_length":request.max_length,
            "top_p":request.top_p,
            "temperature":request.temperature,            
            ** request.extra_params.__dict__,
            ** extract_params}] 
        else: 
            v = [{
            "instruction":self._generate_ins(x,request), 
            "max_length":request.max_length,
            "top_p":request.top_p,
            "temperature":request.temperature,           
            ** request.extra_params.__dict__,
            ** extract_params} for x in request.instruction]         
        res = self._query(model,v) 
        return [LLMResponse(output=item["predict"],input=item["input"]) for item in res]
    
    def apply_sql_func(self,sql:str,data:List[Dict[str,Any]],owner:str="admin",url:str="http://127.0.0.1:9003/model/predict"):
        res = self._rest_byzer_engine(sql,data,owner,url)
        return res
                   
    def _rest_byzer_engine(self, sql:str,table:List[Dict[str,Any]],owner:str,url:str):
        import requests
        import json
        data = {
                'sessionPerUser': 'true',
                'sessionPerRequest': 'true',
                'owner': owner,
                'dataType': 'row',
                'sql': sql,
                'data': json.dumps(table,ensure_ascii=False)
            }
        response = requests.post(url, data=data)
        
        if response.status_code != 200:
            raise Exception(f"{self.url} status:{response.status_code} content: {response.text} request: json/{json.dumps(data,ensure_ascii=False)}")
        res = json.loads(response.text)        
        return res[0]

    def _query(self, model:str, input_value:List[Dict[str,Any]]):
        udf_master = ray.get_actor(model)
        new_input_value = [json.dumps(x,ensure_ascii=False) for x in input_value]
      
        try:
            [index, worker] = ray.get(udf_master.get.remote())
            res = ray.get(worker.async_apply.remote(new_input_value))            
            return json.loads(res["value"][0])
        except Exception as inst:
            raise inst
        finally:
            ray.get(udf_master.give_back.remote(index))        
            