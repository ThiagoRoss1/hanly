//! Keeps the private Python service and its ordinary descendants in one
//! Windows process family while allowing the update helper to break away.

use crate::ipc::BridgeError;
use std::mem::{size_of, zeroed};
use std::os::windows::io::AsRawHandle;
use std::process::Child;
use std::ptr;
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_BREAKAWAY_OK,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};

/// Owns the service's process family. Closing this handle terminates every
/// assigned descendant except a deliberately detached updater helper.
pub(crate) struct WindowsJob {
    handle: HANDLE,
}

// A job handle is an operating-system capability and may safely move with the
// service owner; access to it is otherwise limited to assignment and close.
unsafe impl Send for WindowsJob {}

impl WindowsJob {
    /// Assign a still-suspended service to a kill-on-close family.
    pub(crate) fn attach(child: &Child) -> Result<Self, BridgeError> {
        // SAFETY: A null security descriptor and name request a private unnamed
        // job. The returned handle is owned here until transferred to `Self`.
        let handle = unsafe { CreateJobObjectW(ptr::null(), ptr::null()) };
        if handle.is_null() {
            return Err(start_error());
        }

        // SAFETY: Zero is a valid initial state for the extended limit record;
        // only its documented LimitFlags field is changed before the call.
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        limits.BasicLimitInformation.LimitFlags =
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
        let configured = unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if configured == 0 {
            unsafe { CloseHandle(handle) };
            return Err(start_error());
        }

        // SAFETY: Child owns a live process handle for its lifetime. The job
        // handle is valid and configured above; assignment occurs before resume.
        let assigned = unsafe { AssignProcessToJobObject(handle, child.as_raw_handle() as HANDLE) };
        if assigned == 0 {
            unsafe { CloseHandle(handle) };
            return Err(start_error());
        }

        Ok(Self { handle })
    }

    /// Resume the suspended service's only initial thread after job assignment.
    pub(crate) fn resume(&self, process_id: u32) -> Result<(), BridgeError> {
        let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) };
        if snapshot == (-1_isize) as HANDLE {
            return Err(start_error());
        }

        // SAFETY: Toolhelp requires dwSize to describe the initialized record.
        let mut entry: THREADENTRY32 = unsafe { zeroed() };
        entry.dwSize = size_of::<THREADENTRY32>() as u32;
        let mut found_thread = None;
        let mut has_entry = unsafe { Thread32First(snapshot, &mut entry) } != 0;
        while has_entry {
            if entry.th32OwnerProcessID == process_id {
                found_thread = Some(entry.th32ThreadID);
                break;
            }
            has_entry = unsafe { Thread32Next(snapshot, &mut entry) } != 0;
        }
        unsafe { CloseHandle(snapshot) };

        let Some(thread_id) = found_thread else {
            return Err(start_error());
        };
        let thread = unsafe { OpenThread(THREAD_SUSPEND_RESUME, 0, thread_id) };
        if thread.is_null() {
            return Err(start_error());
        }

        let resumed = unsafe { ResumeThread(thread) };
        unsafe { CloseHandle(thread) };
        if resumed == u32::MAX {
            return Err(start_error());
        }
        Ok(())
    }
}

impl Drop for WindowsJob {
    fn drop(&mut self) {
        // SAFETY: This object uniquely owns the job handle.
        unsafe { CloseHandle(self.handle) };
    }
}

fn start_error() -> BridgeError {
    BridgeError::new(
        "service_start_failed",
        "Hanly could not start its desktop service.",
    )
}
