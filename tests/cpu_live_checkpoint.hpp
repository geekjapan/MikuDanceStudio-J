#pragma once
inline bool CpuPreviewUiCycles(HWND main,DWORD process){
    if(!_wgetenv(L"MDS_RHI_CPU_PREVIEW_UI_TEST"))return true;
    const auto* directory=_wgetenv(L"MDS_RHI_CPU_GEOMETRY_DIR");if(!directory)return false;
    const auto ledger=std::filesystem::path(directory)/("cpu_resident."+std::to_string(process)+".csv");
    const auto count=[&](const char* backend,const char* operation){std::ifstream f(ledger);std::string line;unsigned n=0;
        const auto needle=std::string(",")+backend+","+operation+",PASS,";while(std::getline(f,line))if(line.find(needle)!=std::string::npos)++n;return n;};
    const auto wait=[&](const char* backend,const char* operation,unsigned before){
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(15);
        while(std::chrono::steady_clock::now()<deadline){InvalidateRect(main,nullptr,FALSE);if(count(backend,operation)>before)return true;
            if(!IsWindow(main))return false;std::this_thread::sleep_for(std::chrono::milliseconds(100));}return false;};
    const auto windows=[&](){struct Found{DWORD pid;std::vector<HWND> windows;};Found found{process};
        EnumWindows([](HWND w,LPARAM data)->BOOL{auto& f=*reinterpret_cast<Found*>(data);DWORD pid=0;GetWindowThreadProcessId(w,&pid);
            wchar_t type[64]{};GetClassNameW(w,type,64);if(pid==f.pid && !wcscmp(type,L"MDS_CPU_RHI_PREVIEW"))f.windows.push_back(w);return TRUE;},reinterpret_cast<LPARAM>(&found));return found.windows;};
    const auto waitClosed=[&](const char* backend,unsigned before){
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(15);
        // A posted WM_CLOSE releases the controller before destroying its
        // host window. The release row alone is not a window-close barrier.
        while(std::chrono::steady_clock::now()<deadline){
            if(count(backend,"close")>before && windows().empty())return true;
            if(!IsWindow(main))return false;std::this_thread::sleep_for(std::chrono::milliseconds(100));}
        std::fprintf(stderr,"CPU_PREVIEW_UI close timeout pid=%lu backend=%s\n",process,backend);return false;};
    const auto menu=GetMenu(main);
    if(GetMenuState(menu,0xe110,MF_BYCOMMAND)==UINT(-1) || GetMenuState(menu,0xe112,MF_BYCOMMAND)==UINT(-1))return false;
    SendMessageW(main,WM_COMMAND,0xe100,0);if(!windows().empty())return false;
    for(unsigned cycle=0;cycle<3;++cycle)for(unsigned backend=0;backend<2;++backend){
        const char* name=backend?"dx12":"dx11";const auto before=count(name,"present"),closed=count(name,"close");
        SendMessageW(main,WM_COMMAND,backend?0xe112:0xe110,0);
        if(!wait(name,"present",before) || windows().size()!=1)return false;
        if(!(GetMenuState(menu,backend?0xe112:0xe110,MF_BYCOMMAND)&MF_CHECKED))return false;
        // Exercise both the menu shutdown and the preview's close button.
        if(cycle==1)PostMessageW(windows().front(),WM_CLOSE,0,0);else SendMessageW(main,WM_COMMAND,0xe100,0);
        if(!waitClosed(name,closed))return false;
    }
    SendMessageW(main,WM_COMMAND,0xe113,0);
    if(windows().size()!=2)return false;
    std::printf("CPU_PREVIEW_UI pid=%lu menu_open_close_cycles=3 per_backend PASS\n",process);std::fflush(stdout);return true;
}
inline bool CpuResidentWindowLifecycle(HWND main,DWORD process){
    const auto* mode=_wgetenv(L"MDS_RHI_CPU_SCENE_PREVIEW");if(!mode || !*mode)return true;
    struct Found {DWORD process;std::vector<HWND> windows;};Found found{process};
    EnumWindows([](HWND window,LPARAM data)->BOOL{auto& f=*reinterpret_cast<Found*>(data);DWORD id=0;GetWindowThreadProcessId(window,&id);
        wchar_t type[64]{};GetClassNameW(window,type,64);if(id==f.process && !wcscmp(type,L"MDS_CPU_RHI_PREVIEW") && IsWindowVisible(window))f.windows.push_back(window);return TRUE;},reinterpret_cast<LPARAM>(&found));
    if(found.windows.size()!=(wcscmp(mode,L"both")==0?2u:1u))return false;
    const auto* directory=_wgetenv(L"MDS_RHI_CPU_GEOMETRY_DIR");if(!directory)return false;
    const auto ledger=std::filesystem::path(directory)/("cpu_resident."+std::to_string(process)+".csv");
    const auto count=[&](const char* backend,const char* operation){std::ifstream file(ledger);std::string line;unsigned n=0;
        const auto needle=std::string(",")+backend+","+operation+",PASS,";while(std::getline(file,line))if(line.find(needle)!=std::string::npos)++n;return n;};
    const auto wait=[&](const char* backend,const char* operation,unsigned before){
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(15);
        while(std::chrono::steady_clock::now()<deadline){InvalidateRect(main,nullptr,FALSE);
            if(count(backend,operation)>before)return true;if(!IsWindow(main))return false;
            std::this_thread::sleep_for(std::chrono::milliseconds(100));}
        std::fprintf(stderr,"CPU_RESIDENT timeout pid=%lu backend=%s operation=%s\n",process,backend,operation);return false;};
    for(auto window:found.windows){wchar_t title[128]{};GetWindowTextW(window,title,128);const char* backend=wcsstr(title,L"DX12")?"dx12":"dx11";
        RECT original{};GetWindowRect(window,&original);const auto resized=count(backend,"resize");
        // A scene-sized preview may already fill the desktop. Growing it can
        // be clamped by Win32 and restoring the same extent need not rebuild
        // the swapchain. Use two distinct extents inside the desktop instead.
        const int firstWidth=original.right-original.left==704?672:704;
        if(!SetWindowPos(window,nullptr,0,0,firstWidth,512,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE))return false;
        if(!wait(backend,"resize",resized))return false;
        const auto suspended=count(backend,"suspend");ShowWindow(window,SW_MINIMIZE);if(!wait(backend,"suspend",suspended))return false;
        const auto restored=count(backend,"resize");ShowWindow(window,SW_RESTORE);
        if(!SetWindowPos(window,nullptr,0,0,640,480,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE))return false;
        if(!wait(backend,"resize",restored))return false;
        const auto replaced=count(backend,"replace");PostMessageW(window,WM_APP+0x421,0,0);if(!wait(backend,"replace",replaced))return false;
        const auto presented=count(backend,"present");if(!wait(backend,"present",presented))return false;
        if(!SetWindowPos(window,nullptr,0,0,original.right-original.left,original.bottom-original.top,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE))return false;
        std::printf("CPU_RESIDENT pid=%lu backend=%s resize_minimize_restore_replace=PASS\n",process,backend);std::fflush(stdout);
    }
    return true;
}
// The GUI test owns these requests. The application consumes them only at a
// normal scene-clear boundary and acknowledges after all image/lifecycle gates.
inline bool CpuLiveCheckpoint(HWND main,DWORD process,const char* phase){
    const auto* live=_wgetenv(L"MDS_RHI_CPU_LIVE_HISTORY");if(!live || wcscmp(live,L"1"))return true;
    const auto* directory=_wgetenv(L"MDS_RHI_CPU_GEOMETRY_DIR");if(!directory)return false;
    static std::map<DWORD,unsigned> checkpoints;const unsigned id=++checkpoints[process];
    const auto stem=std::filesystem::path(directory)/("cpu_live.request."+std::to_string(process)+".txt");
    const auto temporary=std::filesystem::path(stem.wstring()+L".tmp");
    {std::ofstream request(temporary);request<<id<<" "<<phase<<"\n";if(!request)return false;}
    if(!MoveFileExW(temporary.c_str(),stem.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))return false;
    const auto ack=std::filesystem::path(directory)/("cpu_live.ack."+std::to_string(process)+".txt");
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);
    while(std::chrono::steady_clock::now()<deadline){
        std::ifstream answer(ack);unsigned completed=0;std::string status;
        if(answer>>completed>>status && completed==id){std::printf("CPU_LIVE pid=%lu checkpoint=%u phase=%s status=%s\n",process,id,phase,status.c_str());std::fflush(stdout);
            return status=="PASS" && (id!=1 || (CpuResidentWindowLifecycle(main,process) && CpuPreviewUiCycles(main,process)));}
        if(!IsWindow(main))return false;
        // Invalid regions coalesce; posting WM_PAINT every poll would queue
        // hundreds of messages while GPU readback blocks the application.
        // Those messages can delay play/stop and the following Save As command.
        InvalidateRect(main,nullptr,FALSE);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    std::fprintf(stderr,"CPU_LIVE timeout pid=%lu checkpoint=%u phase=%s\n",process,id,phase);return false;
}
