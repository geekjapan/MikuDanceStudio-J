"""Read-only NVIDIA DRS antialiasing settings; never save or modify profiles."""
import ctypes as c
import json
import sys
from pathlib import Path
class Value(c.Union):
    _pack_=4
    _fields_=[("dword",c.c_uint32),("data",c.c_ubyte*4100)]
class Setting(c.Structure):
    _pack_=4
    _fields_=[("version",c.c_uint32),("name",c.c_uint16*2048),("id",c.c_uint32),("type",c.c_uint32),("location",c.c_uint32),("predefined",c.c_uint32),("valid",c.c_uint32),("default",Value),("current",Value)]
class Application(c.Structure):
    _fields_=[("version",c.c_uint32),("predefined",c.c_uint32),("name",c.c_uint16*2048),("friendly",c.c_uint16*2048),("launcher",c.c_uint16*2048)]
def main():
    dll=c.CDLL("nvapi64.dll" if c.sizeof(c.c_void_p)==8 else "nvapi.dll")
    query=dll.nvapi_QueryInterface;query.argtypes=[c.c_uint32];query.restype=c.c_void_p
    def fn(number,*args):
        address=query(number)
        if not address:raise RuntimeError(f"NVAPI unavailable {number:x}")
        return c.CFUNCTYPE(c.c_int,*args)(address)
    def checked(result):
        if result:raise RuntimeError(f"NVAPI status {result}")
    checked(fn(0x0150e828)());session=c.c_void_p()
    checked(fn(0x0694d52e,c.POINTER(c.c_void_p))(c.byref(session)))
    try:
        checked(fn(0x375dbd6b,c.c_void_p)(session))
        profiles=[]
        for label,number in [("base",0xda8466a0),("global",0x617bff9f)]:
            profile=c.c_void_p();checked(fn(number,c.c_void_p,c.POINTER(c.c_void_p))(session,c.byref(profile)));profiles.append((label,profile))
        applications=[]
        for executable in ["MikuDanceStudio.exe","rhi_d3d9_msaa_history_test.exe"]:
            name=(c.c_uint16*2048)();encoded=executable.encode("utf-16-le");c.memmove(name,encoded,len(encoded));profile=c.c_void_p();app=Application();app.version=c.sizeof(app)|(1<<16)
            status=fn(0xeee566b2,c.c_void_p,c.c_void_p,c.POINTER(c.c_void_p),c.POINTER(Application))(session,name,c.byref(profile),c.byref(app))
            applications.append({"executable":executable,"findStatus":status})
            if status==0:profiles.append((executable,profile))
        keys={"mode":0x107efc5b,"method":0x10d773d2,"gamma":0x107d639d,"transparency_multisample":0x10fc2d9c,"transparency_supersample":0x10d48a85,"behavior":0x10ecdb82,"fxaa":0x1074c972,"mfaa":0x0098c1ac}
        report={"readOnly":True,"applications":applications,"profiles":{}}
        for label,profile in profiles:
            values={}
            for name,key in keys.items():
                setting=Setting();setting.version=c.sizeof(setting)|(1<<16);setting.id=key
                status=fn(0x73bf8338,c.c_void_p,c.c_void_p,c.c_uint32,c.POINTER(Setting))(session,profile,key,c.byref(setting))
                values[name]={"id":hex(key),"status":status}
                if status==0:values[name].update(value=setting.current.dword,location=setting.location,predefined=setting.predefined,type=setting.type)
            report["profiles"][label]=values
        output=Path(sys.argv[1]);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8");print(json.dumps(report,indent=2))
    finally:fn(0xdad9cff8,c.c_void_p)(session)
if __name__=="__main__":main()
