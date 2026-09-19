/** UUID v4 for commands and local record IDs, including plain-HTTP LAN browsers. */
export function newId():string {
 if(typeof globalThis.crypto.randomUUID==='function')return globalThis.crypto.randomUUID();
 // getRandomValues remains available outside secure contexts; randomUUID does not.
 const bytes=globalThis.crypto.getRandomValues(new Uint8Array(16));
 bytes[6]=(bytes[6]&0x0f)|0x40;
 bytes[8]=(bytes[8]&0x3f)|0x80;
 const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
 return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
