#define WIN32_LEAN_AND_MEAN
#include <Windows.h>
#include <string>
#include <vector>
#include <cstdio>
#include <chrono>
#include <thread>
#include <filesystem>
struct Windows {DWORD process;HWND main=nullptr;std::vector<HWND> previews,dialogs;};
Windows Snapshot(DWORD process){
    Windows found{process};EnumWindows([](HWND w,LPARAM data)->BOOL{
        auto& f=*reinterpret_cast<Windows*>(data);DWORD pid=0;GetWindowThreadProcessId(w,&pid);if(pid!=f.process)return TRUE;
        wchar_t type[128]{};GetClassNameW(w,type,128);
        if(!wcscmp(type,L"Polygon Movie Maker"))f.main=w;
        else if(!wcscmp(type,L"MDS_CPU_RHI_PREVIEW"))f.previews.push_back(w);
        else if(!wcscmp(type,L"#32770"))f.dialogs.push_back(w);return TRUE;
    },reinterpret_cast<LPARAM>(&found));return found;
}
template<class Predicate>bool Wait(Predicate ready,unsigned seconds=20){
    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(seconds);
    do{if(ready())return true;std::this_thread::sleep_for(std::chrono::milliseconds(100));}while(std::chrono::steady_clock::now()<until);return false;
}
int wmain(int argc,wchar_t** argv){
    if(argc!=3)return 1;
    auto exe=std::filesystem::absolute(argv[1]);auto fixture=std::filesystem::absolute(argv[2]);
    // The native acceptance environment is explicitly absent in this test.
    for(const auto* name:{L"MDS_RHI_CPU_SCENE_PREVIEW",L"MDS_RHI_CPU_GEOMETRY",L"MDS_RHI_CPU_INPUTS",L"MDS_RHI_CPU_INPUTS_AUDIT",
        L"MDS_RHI_CPU_INPUTS_ACCEPTED",L"MDS_RHI_CPU_MIP_PREPARE",L"MDS_RHI_CPU_FULL_SCENE",L"MDS_RHI_HISTORY_REPLAY",
        L"MDS_RHI_CPU_LIVE_HISTORY",L"MDS_RHI_CPU_GEOMETRY_DIR",L"MDS_RHI_MODEL_NO_MME"})SetEnvironmentVariableW(name,nullptr);
    std::wstring cmd=L"\""+exe.wstring()+L"\" \""+fixture.wstring()+L"\"";std::vector<wchar_t> command(cmd.begin(),cmd.end());command.push_back(0);
    STARTUPINFOW startup{sizeof(startup)};struct Child{PROCESS_INFORMATION info{};HANDLE job=CreateJobObjectW(nullptr,nullptr);
        ~Child(){if(job)CloseHandle(job);if(info.hThread)CloseHandle(info.hThread);if(info.hProcess)CloseHandle(info.hProcess);}}child;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limit{};limit.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if(!child.job || !SetInformationJobObject(child.job,JobObjectExtendedLimitInformation,&limit,sizeof(limit)))return 1;
    if(!CreateProcessW(exe.c_str(),command.data(),nullptr,nullptr,FALSE,CREATE_SUSPENDED,nullptr,exe.parent_path().c_str(),&startup,&child.info))return 1;
    if(!AssignProcessToJobObject(child.job,child.info.hProcess)){TerminateProcess(child.info.hProcess,1);return 1;}ResumeThread(child.info.hThread);
    HWND main=nullptr;
    if(!Wait([&](){auto w=Snapshot(child.info.dwProcessId);main=w.main;return main && GetDlgItem(main,436) && SendMessageW(GetDlgItem(main,436),CB_GETCOUNT,0,0)>1;}))return 2;
    if(!Snapshot(child.info.dwProcessId).previews.empty())return 3;
    // Select the documented supported screen source through the real menu.
    SendMessageW(main,WM_COMMAND,246,0);
    // Turn off the existing MME effect policy through its actual command,
    // rather than using the diagnostic device-registration bypass.
    SendMessageW(main,WM_COMMAND,40006,0);
    for(unsigned cycle=0;cycle<3;++cycle)for(unsigned backend=0;backend<2;++backend){
        const unsigned id=backend?0xe112:0xe110;
        if(GetMenuState(GetMenu(main),id,MF_BYCOMMAND)==UINT(-1))return 4;
        SendMessageW(main,WM_COMMAND,id,0);
        if(!Wait([&](){auto w=Snapshot(child.info.dwProcessId);InvalidateRect(main,nullptr,FALSE);
            if(w.previews.size()!=1 || !IsWindowVisible(w.previews[0]))return false;
            const auto status=FindWindowExW(w.previews[0],nullptr,L"STATIC",nullptr);
            if(IsWindowVisible(status)){char text[512]{};GetWindowTextA(status,text,sizeof(text));std::fprintf(stderr,"%s\n",text);return false;}
            return w.dialogs.empty();}))return 5;
        auto windows=Snapshot(child.info.dwProcessId);
        if(cycle==1)PostMessageW(windows.previews[0],WM_CLOSE,0,0);else SendMessageW(main,WM_COMMAND,0xe100,0);
        if(!Wait([&](){return Snapshot(child.info.dwProcessId).previews.empty();}))return 6;
    }
    std::puts("PASS production menu: runtime default off; CPU preview without capture environment; three open/close cycles per backend");return 0;
}
