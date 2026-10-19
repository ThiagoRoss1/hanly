use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::{self, BufRead};

pub const MAX_FRAME: usize = 1024 * 1024;
pub const MAX_PENDING: usize = 32;
pub const MAX_SEQUENCE: u64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct BridgeError {
    pub code: String,
    pub message: String,
}

impl BridgeError {
    pub fn new(code: &str, message: &str) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
pub enum Message {
    #[serde(rename = "reply")]
    Reply {
        version: u8,
        id: String,
        result: Option<Value>,
        error: Option<BridgeError>,
    },
    #[serde(rename = "event")]
    Event {
        version: u8,
        sequence: u64,
        event: String,
        payload: Value,
    },
}

pub fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-._:".contains(&c))
}

pub fn decode(bytes: &[u8]) -> Result<Message, BridgeError> {
    if bytes.len() > MAX_FRAME {
        return Err(protocol_error());
    }
    let value: StrictValue = serde_json::from_slice(bytes).map_err(|_| protocol_error())?;
    if !bounded_depth(&value.0, 0) {
        return Err(protocol_error());
    }
    let message: Message = serde_json::from_value(value.0).map_err(|_| protocol_error())?;
    match &message {
        Message::Reply {
            version,
            id,
            result,
            error,
        } => {
            if *version != 1
                || !valid_id(id)
                || result.is_some() == error.is_some()
                || result.as_ref().is_some_and(|v| !v.is_object())
                || error.as_ref().is_some_and(|e| {
                    e.code.is_empty() || e.code.len() > 64 || e.message.len() > 4096
                })
            {
                return Err(protocol_error());
            }
        }
        Message::Event {
            version,
            sequence,
            event,
            payload,
        } => {
            if *version != 1
                || *sequence == 0
                || *sequence > MAX_SEQUENCE
                || !payload.is_object()
                || ![
                    "state",
                    "popup",
                    "popup_hide",
                    "service_status",
                    "native_action",
                    "trace",
                ]
                .contains(&event.as_str())
                    && !(cfg!(debug_assertions) && event == "lab_capture")
            {
                return Err(protocol_error());
            }
        }
    }
    Ok(message)
}

fn bounded_depth(value: &Value, depth: usize) -> bool {
    if depth > 32 {
        return false;
    }
    match value {
        Value::Array(values) => values.iter().all(|v| bounded_depth(v, depth + 1)),
        Value::Object(values) => values.values().all(|v| bounded_depth(v, depth + 1)),
        _ => true,
    }
}

// Duplicate object keys can change command meaning between two decoders.
struct StrictValue(Value);

impl<'de> Deserialize<'de> for StrictValue {
    fn deserialize<D: serde::Deserializer<'de>>(decoder: D) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = StrictValue;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("unambiguous JSON")
            }
            fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Self::Value, E> {
                Ok(StrictValue(v.into()))
            }
            fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Self::Value, E> {
                Ok(StrictValue(v.into()))
            }
            fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Self::Value, E> {
                Ok(StrictValue(v.into()))
            }
            fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Self::Value, E> {
                serde_json::Number::from_f64(v)
                    .map(|v| StrictValue(Value::Number(v)))
                    .ok_or_else(|| E::custom("nonfinite number"))
            }
            fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Self::Value, E> {
                Ok(StrictValue(v.into()))
            }
            fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Self::Value, E> {
                Ok(StrictValue(v.into()))
            }
            fn visit_none<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(StrictValue(Value::Null))
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
                Ok(StrictValue(Value::Null))
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut sequence: A,
            ) -> Result<Self::Value, A::Error> {
                let mut values = Vec::new();
                while let Some(value) = sequence.next_element::<StrictValue>()? {
                    values.push(value.0);
                }
                Ok(StrictValue(Value::Array(values)))
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<Self::Value, A::Error> {
                let mut values = serde_json::Map::new();
                while let Some((key, value)) = map.next_entry::<String, StrictValue>()? {
                    if values.insert(key, value.0).is_some() {
                        return Err(serde::de::Error::custom("duplicate key"));
                    }
                }
                Ok(StrictValue(Value::Object(values)))
            }
        }
        decoder.deserialize_any(Visitor)
    }
}

pub fn read_frame(reader: &mut impl BufRead) -> io::Result<Option<Vec<u8>>> {
    let mut frame = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            return if frame.is_empty() {
                Ok(None)
            } else {
                Err(io::ErrorKind::UnexpectedEof.into())
            };
        }
        let end = available.iter().position(|c| *c == b'\n');
        let count = end.map_or(available.len(), |n| n + 1);
        if frame.len() + count > MAX_FRAME + 2 {
            return Err(io::ErrorKind::InvalidData.into());
        }
        frame.extend_from_slice(&available[..count]);
        reader.consume(count);
        if end.is_some() {
            frame.pop();
            if frame.last() == Some(&b'\r') {
                frame.pop();
            }
            if frame.len() > MAX_FRAME {
                return Err(io::ErrorKind::InvalidData.into());
            }
            return Ok(Some(frame));
        }
    }
}

pub fn protocol_error() -> BridgeError {
    BridgeError::new(
        "protocol_error",
        "The desktop service sent an invalid message.",
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn rejects_ambiguous_and_unsolicited_envelopes() {
        for frame in [
            r#"{"version":1,"type":"reply","id":"1","result":{},"error":{"code":"x","message":"x"}}"#,
            r#"{"version":1,"type":"reply","id":"","result":{}}"#,
            r#"{"version":2,"type":"reply","id":"1","result":{}}"#,
            r#"{"version":1,"type":"reply","id":"1","result":{},"extra":true}"#,
            r#"{"version":1,"type":"reply","id":"1","id":"2","result":{}}"#,
            r#"{"version":1,"type":"reply","id":"1","result":{"theme":"light","theme":"dark"}}"#,
            r#"{"version":1,"type":"event","sequence":0,"event":"state","payload":{}}"#,
        ] {
            assert!(decode(frame.as_bytes()).is_err(), "{frame}");
        }
        assert!(decode(br#"{"version":1,"type":"reply","id":"native-1","result":{}}"#).is_ok());
    }

    #[test]
    fn bounds_allocations_and_requires_a_complete_frame() {
        assert!(read_frame(&mut Cursor::new(vec![b'x'; MAX_FRAME + 2])).is_err());
        assert!(read_frame(&mut Cursor::new(b"partial")).is_err());
        let mut input = Cursor::new(b"one\ntwo\n");
        assert_eq!(read_frame(&mut input).unwrap(), Some(b"one".to_vec()));
        assert_eq!(read_frame(&mut input).unwrap(), Some(b"two".to_vec()));
        assert_eq!(read_frame(&mut input).unwrap(), None);
    }
}
