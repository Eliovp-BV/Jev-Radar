"""Network policy enforced independently of model output."""
import asyncio, ipaddress, socket, re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote
from aiohttp.abc import AbstractResolver

class PolicyError(ValueError): pass
SENSITIVE=re.compile(r'(token|secret|key|password|auth|signature|session|code)',re.I)

def public_ip(address):
    ip=ipaddress.ip_address(address.split('%')[0])
    if not ip.is_global or ip.is_multicast or ip.is_reserved: raise PolicyError('Non-public network destination rejected')
    if isinstance(ip,ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo):
        raise PolicyError('IPv6 transition address rejected')
    return str(ip)

def validate_url(url):
    if len(url)>2048 or any(ord(c)<33 for c in url) or '\\' in url: raise PolicyError('Malformed URL')
    try:
        p=urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password: raise PolicyError('Only public HTTP(S) URLs without credentials are allowed')
        if p.port and p.port not in (80,443): raise PolicyError('Only standard web ports are allowed')
        host=p.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if '%' in host or host in ('localhost','metadata.google.internal') or host.endswith(('.localhost','.local','.internal')): raise PolicyError('Local hostname rejected')
        try: public_ip(host)
        except ValueError as e:
            if isinstance(e,PolicyError): raise
            if re.fullmatch(r'[\d.xXa-fA-F]+',host) and (host.startswith(('0x','0X')) or host.replace('.','').isdigit()): raise PolicyError('Encoded IP rejected')
        if any(SENSITIVE.search(k) for k,v in parse_qsl(p.query)): raise PolicyError('Credential-like URL parameters are not accepted')
        authority=('['+host+']') if ':' in host else host
        return urlunsplit((p.scheme,authority,p.path or '/',p.query,''))
    except (ValueError,UnicodeError) as e:
        if isinstance(e,PolicyError): raise
        raise PolicyError('Invalid URL') from None

class PublicResolver(AbstractResolver):
    async def resolve(self,host,port=0,family=socket.AF_UNSPEC):
        addresses=await asyncio.get_running_loop().getaddrinfo(host,port,type=socket.SOCK_STREAM,family=family)
        result=[]
        for fam,_,proto,_,sockaddr in addresses:
            ip=public_ip(sockaddr[0])
            result.append({'hostname':host,'host':ip,'port':port,'family':fam,'proto':proto,'flags':socket.AI_NUMERICHOST})
        if not result: raise PolicyError('No public DNS addresses')
        return result
    async def close(self): pass

def redact(text,secrets=()):
    text=str(text)
    for secret in secrets:
        if secret: text=text.replace(secret,'[REDACTED]')
    text=re.sub(r'(?i)(Bearer\s+)\S+',r'\1[REDACTED]',text)
    return re.sub(r'(?i)([?&](?:[^=&]*(?:key|token|secret|auth|signature|session)[^=&]*)=)[^&\s]+',r'\1[REDACTED]',text)[:1000]

def csv_safe(value):
    s='' if value is None else str(value)
    return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s
