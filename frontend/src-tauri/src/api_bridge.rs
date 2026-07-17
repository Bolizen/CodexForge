use std::{
    io::{Read, Write},
    net::TcpStream,
    sync::Arc,
    time::Duration,
};

use serde_json::{json, Value};
use tauri::State;

use crate::backend::{BackendEndpoint, BackendSupervisor};

const MAX_API_PATH_BYTES: usize = 2_048;
const MAX_API_BODY_BYTES: usize = 1_048_576;
const MAX_API_RESPONSE_BYTES: usize = 16 * 1_048_576;
const API_IO_TIMEOUT: Duration = Duration::from_secs(10);
const ALLOWED_METHODS: [&str; 5] = ["GET", "POST", "PUT", "PATCH", "DELETE"];

#[tauri::command]
pub(crate) async fn api_request(
    state: State<'_, Arc<BackendSupervisor>>,
    path: String,
    method: String,
    body: Option<Value>,
) -> Result<Value, String> {
    let request = ValidatedRequest::new(path, method, body).map_err(|error| error.to_string())?;
    let endpoint = state
        .endpoint()
        .ok_or_else(|| "The Glacial backend is not available.".to_string())?;
    let forwarded =
        tauri::async_runtime::spawn_blocking(move || forward_request(&endpoint, &request))
            .await
            .map_err(|_| "Glacial could not complete the backend request.".to_string())?;
    let (status, body) =
        forwarded.map_err(|_| "Glacial could not contact its backend.".to_string())?;
    Ok(json!({ "status": status, "body": body }))
}

struct ValidatedRequest {
    path: String,
    method: String,
    body: Option<Vec<u8>>,
}

impl ValidatedRequest {
    fn new(path: String, method: String, body: Option<Value>) -> Result<Self, &'static str> {
        validate_api_path(&path)?;
        if !ALLOWED_METHODS.contains(&method.as_str()) {
            return Err("Unsupported Glacial API method.");
        }

        let body = match body {
            Some(value) => {
                if method == "GET" {
                    return Err("GET requests cannot contain API request data.");
                }
                let serialized = serde_json::to_vec(&value)
                    .map_err(|_| "Glacial API request data is not valid JSON.")?;
                if serialized.len() > MAX_API_BODY_BYTES {
                    return Err("Glacial API request data is too large.");
                }
                Some(serialized)
            }
            None => None,
        };
        Ok(Self { path, method, body })
    }
}

fn validate_api_path(path: &str) -> Result<(), &'static str> {
    if path.is_empty()
        || path.len() > MAX_API_PATH_BYTES
        || !path.starts_with("/api/")
        || path.contains('#')
        || path.contains('\\')
        || path.bytes().any(|byte| byte.is_ascii_control())
    {
        return Err("Invalid Glacial API path.");
    }
    let path_only = path.split_once('?').map_or(path, |(value, _)| value);
    let decoded = percent_decode(path_only.as_bytes())?;
    let decoded = std::str::from_utf8(&decoded).map_err(|_| "Invalid Glacial API path.")?;
    if !decoded.starts_with("/api/")
        || decoded.contains('\\')
        || decoded.bytes().any(|byte| byte.is_ascii_control())
        || decoded
            .split('/')
            .skip(1)
            .any(|segment| segment.is_empty() || segment == "." || segment == "..")
    {
        return Err("Invalid Glacial API path.");
    }
    Ok(())
}

fn percent_decode(value: &[u8]) -> Result<Vec<u8>, &'static str> {
    let mut decoded = Vec::with_capacity(value.len());
    let mut index = 0;
    while index < value.len() {
        if value[index] == b'%' {
            if index + 2 >= value.len() {
                return Err("Invalid Glacial API path.");
            }
            let high = hex_value(value[index + 1]).ok_or("Invalid Glacial API path.")?;
            let low = hex_value(value[index + 2]).ok_or("Invalid Glacial API path.")?;
            decoded.push((high << 4) | low);
            index += 3;
        } else {
            decoded.push(value[index]);
            index += 1;
        }
    }
    Ok(decoded)
}

fn hex_value(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn forward_request(
    endpoint: &BackendEndpoint,
    request: &ValidatedRequest,
) -> Result<(u16, Value), ()> {
    let mut stream =
        TcpStream::connect_timeout(&endpoint.address, API_IO_TIMEOUT).map_err(|_| ())?;
    stream
        .set_read_timeout(Some(API_IO_TIMEOUT))
        .map_err(|_| ())?;
    stream
        .set_write_timeout(Some(API_IO_TIMEOUT))
        .map_err(|_| ())?;

    let mut head = format!(
        "{} {} HTTP/1.1\r\nHost: {}\r\nAuthorization: Bearer {}\r\nAccept: application/json\r\nConnection: close\r\n",
        request.method, request.path, endpoint.address, endpoint.token
    );
    if let Some(body) = &request.body {
        head.push_str(&format!(
            "Content-Type: application/json\r\nContent-Length: {}\r\n",
            body.len()
        ));
    }
    head.push_str("\r\n");
    stream.write_all(head.as_bytes()).map_err(|_| ())?;
    if let Some(body) = &request.body {
        stream.write_all(body).map_err(|_| ())?;
    }

    let response = read_bounded_response(&mut stream)?;
    parse_http_response(&response)
}

fn read_bounded_response(stream: &mut TcpStream) -> Result<Vec<u8>, ()> {
    let mut response = Vec::new();
    let mut chunk = [0_u8; 8_192];
    loop {
        let count = stream.read(&mut chunk).map_err(|_| ())?;
        if count == 0 {
            break;
        }
        if response.len().saturating_add(count) > MAX_API_RESPONSE_BYTES {
            return Err(());
        }
        response.extend_from_slice(&chunk[..count]);
    }
    Ok(response)
}

fn parse_http_response(response: &[u8]) -> Result<(u16, Value), ()> {
    let separator = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or(())?;
    if separator > 65_536 {
        return Err(());
    }
    let headers = std::str::from_utf8(&response[..separator]).map_err(|_| ())?;
    let body = &response[separator + 4..];
    let mut lines = headers.lines();
    let status_line = lines.next().ok_or(())?;
    let mut status_parts = status_line.split_whitespace();
    if status_parts.next() != Some("HTTP/1.1") {
        return Err(());
    }
    let status = status_parts
        .next()
        .ok_or(())?
        .parse::<u16>()
        .map_err(|_| ())?;
    if !(100..=599).contains(&status) {
        return Err(());
    }

    let mut content_length = None;
    for line in lines {
        let (name, value) = line.split_once(':').ok_or(())?;
        if name.eq_ignore_ascii_case("transfer-encoding") {
            return Err(());
        }
        if name.eq_ignore_ascii_case("content-length") {
            if content_length.is_some() {
                return Err(());
            }
            content_length = Some(value.trim().parse::<usize>().map_err(|_| ())?);
        }
    }
    if content_length.is_some_and(|length| length != body.len()) {
        return Err(());
    }
    let body = if body.is_empty() {
        json!({})
    } else {
        serde_json::from_slice(body).unwrap_or_else(|_| json!({}))
    };
    Ok((status, body))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bridge_rejects_generic_proxy_and_traversal_paths() {
        for path in [
            "http://127.0.0.1:9000/api/health",
            "//127.0.0.1/api/health",
            "/api/../health",
            "/api/%2e%2e/health",
            "/api/%2F%2Fevil.test",
            "/api/health#fragment",
            "/api\\health",
            "/api/health%",
        ] {
            assert_eq!(validate_api_path(path), Err("Invalid Glacial API path."));
        }
        assert!(validate_api_path("/api/projects?project_path=C%3A%5Cworkspace%5Cproject").is_ok());
    }

    #[test]
    fn bridge_allows_only_existing_methods_and_bounded_json() {
        assert!(ValidatedRequest::new("/api/projects".into(), "GET".into(), None).is_ok());
        assert!(ValidatedRequest::new(
            "/api/projects".into(),
            "POST".into(),
            Some(json!({ "name": "Example" }))
        )
        .is_ok());
        assert!(ValidatedRequest::new("/api/projects".into(), "CONNECT".into(), None).is_err());
        assert!(ValidatedRequest::new(
            "/api/projects".into(),
            "POST".into(),
            Some(Value::String("x".repeat(MAX_API_BODY_BYTES + 1)))
        )
        .is_err());
    }

    #[test]
    fn response_parser_preserves_status_and_json_detail() {
        let response = b"HTTP/1.1 409 Conflict\r\ncontent-type: application/json\r\ncontent-length: 21\r\n\r\n{\"detail\":\"Conflict\"}";
        let (status, body) = parse_http_response(response).unwrap();
        assert_eq!(status, 409);
        assert_eq!(body, json!({ "detail": "Conflict" }));
    }
}
