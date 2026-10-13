use crate::ipc::BridgeError;
use std::path::PathBuf;

#[derive(Clone, Default)]
pub struct LaunchOptions {
    pub runtime_config: Option<PathBuf>,
    pub app_config: Option<PathBuf>,
    pub roi: Option<String>,
    pub update_ready: Option<PathBuf>,
    pub update_challenge: Option<PathBuf>,
    pub self_check: Option<String>,
    pub self_check_image: Option<PathBuf>,
    pub trace: bool,
}

impl LaunchOptions {
    pub fn parse(args: impl IntoIterator<Item = String>) -> Result<Self, BridgeError> {
        let mut args = args.into_iter();
        let mut options = Self::default();
        while let Some(arg) = args.next() {
            if arg == "run" {
                continue;
            }
            if arg == "--trace" {
                options.trace = true;
                continue;
            }
            let value = args.next().ok_or_else(|| invalid_argument(&arg))?;
            if value.is_empty() {
                return Err(invalid_argument(&arg));
            }
            match arg.as_str() {
                "--runtime-config" => options.runtime_config = Some(value.into()),
                "--app-config" => options.app_config = Some(value.into()),
                "--roi" => {
                    let (width, height) = value
                        .split_once('x')
                        .ok_or_else(|| invalid_argument(&arg))?;
                    if ![width, height]
                        .iter()
                        .all(|n| n.parse::<u32>().is_ok_and(|n| n > 0 && n <= 4096))
                    {
                        return Err(invalid_argument(&arg));
                    }
                    options.roi = Some(value);
                }
                "--update-ready" => options.update_ready = Some(value.into()),
                "--update-ready-v2" => options.update_challenge = Some(value.into()),
                "--self-check"
                    if ["inventory", "ocr", "worker", "ui"].contains(&value.as_str()) =>
                {
                    options.self_check = Some(value)
                }
                "--self-check-image" => options.self_check_image = Some(value.into()),
                _ => return Err(invalid_argument(&arg)),
            }
        }
        Ok(options)
    }
}

fn invalid_argument(argument: &str) -> BridgeError {
    BridgeError::new(
        "invalid_argument",
        &format!("Invalid Hanly launch argument: {argument}"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn launch_options_do_not_accept_arbitrary_process_or_url_flags() {
        let args = [
            "run",
            "--runtime-config",
            "/tmp/runtime.json",
            "--roi",
            "200x100",
        ]
        .map(str::to_string);
        let options = LaunchOptions::parse(args).unwrap();
        assert_eq!(options.roi.as_deref(), Some("200x100"));
        assert!(LaunchOptions::parse(["--exec", "command"].map(str::to_string)).is_err());
        assert!(LaunchOptions::parse(["--roi", "0x100"].map(str::to_string)).is_err());
        assert!(LaunchOptions::parse(["--app-config"].map(str::to_string)).is_err());
    }
}
