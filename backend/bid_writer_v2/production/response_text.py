import re


_BOILERPLATE = (
    r"响应(?:措施|说明|方案|内容)|说明如下|具体如下|"
    r"(?:针对|根据|遵照|按照)(?:本项目|本工程|本标段|上述|招标文件|招标)?(?:要求|条款)|"
    r"(?:现)?(?:作|做)(?:如下)?(?:详细)?说明(?:并逐项响应)?|"
    r"(?:按(?:照)?(?:上述|招标(?:文件)?)?要求)(?:落实|执行|实施)|"
    r"(?:我方)?(?:严格|完全|全部|逐项|逐条)?响应(?:招标(?:文件)?要求)?|"
    r"(?:我方)?(?:严格|完全|全部)?(?:满足|符合|执行|落实)(?:招标(?:文件)?|上述|相关)?(?:要求|规定|条款)|"
    r"如下|以上|REQ\d+"
)


def _strip_boilerplate(value: str) -> str:
    """Remove known response labels, never arbitrary short construction text."""
    previous = None
    while value != previous:
        previous = value
        value = re.sub(r"^(?:" + _BOILERPLATE + r")|(?:" + _BOILERPLATE + r")$", "", value, flags=re.IGNORECASE)
    return value


def copies_requirement(text: str, requirement: dict) -> bool:
    """The tender's demand, even with a label, is not a proposed response."""
    compact = lambda value: re.sub(r"[\s#*_`>\-:：，,。；;、！？!?（）()\[\]【】“”\"'‘’]", "", str(value or ""))
    source = compact(requirement.get("content"))
    candidate = compact(text)
    key = compact(requirement.get("requirement_key"))
    if key and candidate.startswith(key):
        candidate = candidate[len(key):]
    if not source or not candidate:
        return False
    if candidate == source:
        return True
    candidate = _strip_boilerplate(candidate)
    if candidate == source or (len(candidate) >= 12 and candidate in source):
        return True
    # Repeating a copied passage adds no proposal, including a repeated
    # subclause from a longer tender requirement.
    repeated = re.fullmatch(r"(.{12,}?)\1+", candidate)
    if repeated and repeated.group(1) in source:
        return True
    if source in candidate:
        remainder = _strip_boilerplate(candidate.replace(source, ""))
        return not remainder or (len(remainder) >= 12 and remainder in source)
    return False
