#[cfg(not(debug_assertions))]
use std::{io, mem::size_of, ptr};

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
#[cfg(any(not(debug_assertions), test))]
use windows_sys::Win32::System::JobObjects::{
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
#[cfg(not(debug_assertions))]
use windows_sys::Win32::System::{
    JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject,
    },
    Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE},
};

pub(crate) struct JobObject(HANDLE);

unsafe impl Send for JobObject {}
unsafe impl Sync for JobObject {}

impl JobObject {
    #[cfg(not(debug_assertions))]
    pub(crate) fn assign_process(process_id: u32) -> io::Result<Self> {
        let job = unsafe { CreateJobObjectW(ptr::null(), ptr::null()) };
        if job.is_null() {
            return Err(io::Error::last_os_error());
        }

        let information = kill_on_close_information();
        let configured = unsafe {
            SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                (&information as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if configured == 0 {
            let error = io::Error::last_os_error();
            unsafe { CloseHandle(job) };
            return Err(error);
        }

        let process = unsafe { OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, process_id) };
        if process.is_null() {
            let error = io::Error::last_os_error();
            unsafe { CloseHandle(job) };
            return Err(error);
        }

        let assigned = unsafe { AssignProcessToJobObject(job, process) };
        let assignment_error = (assigned == 0).then(io::Error::last_os_error);
        unsafe { CloseHandle(process) };
        if let Some(error) = assignment_error {
            unsafe { CloseHandle(job) };
            return Err(error);
        }
        Ok(Self(job))
    }
}

impl Drop for JobObject {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

#[cfg(not(debug_assertions))]
pub(crate) struct ProcessWaitHandle(HANDLE);

#[cfg(not(debug_assertions))]
impl ProcessWaitHandle {
    pub(crate) fn open(process_id: u32) -> io::Result<Self> {
        use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;

        let handle = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, process_id) };
        if handle.is_null() {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(handle))
    }

    pub(crate) fn wait(&self, timeout_millis: u32) -> io::Result<()> {
        use windows_sys::Win32::{
            Foundation::WAIT_OBJECT_0, System::Threading::WaitForSingleObject,
        };

        let result = unsafe { WaitForSingleObject(self.0, timeout_millis) };
        if result == WAIT_OBJECT_0 {
            Ok(())
        } else {
            Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "backend process did not terminate within the bounded wait",
            ))
        }
    }
}

#[cfg(not(debug_assertions))]
impl Drop for ProcessWaitHandle {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

#[cfg(any(not(debug_assertions), test))]
fn kill_on_close_information() -> JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
    let mut information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
    information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    information
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_configuration_is_kill_on_last_handle_close() {
        let information = kill_on_close_information();
        assert_eq!(
            information.BasicLimitInformation.LimitFlags,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        );
    }
}
