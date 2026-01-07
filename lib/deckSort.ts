const DIGIT_MAP: Record<string, number> = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
};

function parseChineseNumber(input: string): number | null {
    if (DIGIT_MAP[input] != null) return DIGIT_MAP[input];
    const match = input.match(/^([一二三四五六七八九两])?十([一二三四五六七八九])?$/);
    if (!match) return null;
    const tens = match[1] ? DIGIT_MAP[match[1]] : 1;
    const ones = match[2] ? DIGIT_MAP[match[2]] : 0;
    return tens * 10 + ones;
}

export function parseLeadingNumber(name: string): number | null {
    const head = name.split(/[_\s]/)[0] || "";
    const leadingDigits = head.match(/^\d+/)?.[0];
    if (leadingDigits) {
        const direct = Number(leadingDigits);
        return Number.isNaN(direct) ? null : direct;
    }

    const leadingChinese = head.match(/^[零〇一二两三四五六七八九十]+/)?.[0];
    if (leadingChinese) {
        return parseChineseNumber(leadingChinese);
    }

    return null;
}

export function compareDeckSegments(nameA: string, nameB: string): number {
    let nextA = nameA;
    let nextB = nameB;
    const maxPrefix = Math.min(nameA.length, nameB.length);
    let prefixLen = 0;
    while (prefixLen < maxPrefix && nameA[prefixLen] === nameB[prefixLen]) {
        prefixLen += 1;
    }
    if (prefixLen > 0) {
        nextA = nameA.slice(prefixLen).replace(/^[\s_-]+/, "");
        nextB = nameB.slice(prefixLen).replace(/^[\s_-]+/, "");
        if (!nextA) nextA = nameA;
        if (!nextB) nextB = nameB;
    }

    const na = parseLeadingNumber(nextA);
    const nb = parseLeadingNumber(nextB);
    if (na != null && nb != null && na !== nb) return na - nb;
    if (na != null && nb == null) return -1;
    if (na == null && nb != null) return 1;
    return nameA < nameB ? -1 : nameA > nameB ? 1 : 0;
}

export function getLastSegment(path: string): string {
    const parts = path.split("/").filter(Boolean);
    return parts.length > 0 ? parts[parts.length - 1] : path;
}

export function compareDeckTitlesByPath(pathA: string, pathB: string): number {
    return compareDeckSegments(getLastSegment(pathA), getLastSegment(pathB));
}
