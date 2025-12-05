/**
 * quizFormat.ts
 *
 * 统一定义测验系统中 card.front / card.back 的数据格式，以及常用工具函数。
 *
 * 设计原则：
 * - front：描述题目“长什么样”（题型、分值、题干、选项、媒体…）
 * - back：描述题目“答案是什么”（answers + explanation）
 * - 判题逻辑由 front.type + options + back.answers 决定
 *
 * ===========================
 * 一、front 字段格式（FrontSchema）
 * ===========================
 *
 * front 是一个 JSON 字符串（或旧数据中的纯文本），解析后结构为：
 *
 * interface FrontSchema {
 *   version: 1;                 // 结构版本号，方便未来演进
 *   type: QuestionType;         // 题目类型
 *   score: number;              // 本题分值
 *   prompt: string;             // 题干文本（填空题可包含 {{1}}、{{2}} 这样的占位符）
 *   options?: string[];         // 单选 / 多选题的选项文本数组，下标 0/1/2/... 对应 A/B/C/...
 *   media?: {
 *     imageUrl?: string;
 *     audioUrl?: string;
 *     videoUrl?: string;
 *   };
 * }
 *
 * QuestionType 支持四种：
 *   - "basic"           简答 / 说明性题目，通常只有一段 prompt 和一个答案
 *   - "single_choice"   单选题
 *   - "multiple_choice" 多选题
 *   - "fill_in_blank"   填空题（空的数量由 prompt 中的 {{n}} 自动推断）
 *
 * 约定：
 *   - basic：一般不需要 options；
 *   - single_choice / multiple_choice：必须提供 options（字符串数组）；
 *   - fill_in_blank：一般不需要 options，空的数量由 prompt 中的 {{数字}} 决定。
 *
 * 旧数据兼容（front）：
 *   - 如果 front 不是合法 JSON，而是普通字符串，则一律视为 basic 类型：
 *       {
 *         version: 1,
 *         type: "basic",
 *         score: 1,
 *         prompt: "<原字符串>",
 *         options: undefined,
 *         media: undefined
 *       }
 *
 * ===========================
 * 二、back 字段格式（BackSchema）
 * ===========================
 *
 * back 是一个 JSON 字符串（或旧数据中的纯文本），解析后结构为：
 *
 * interface BackSchema {
 *   answers: string[][];     // 二维字符串数组：每个“槽位（slot）”对应一组候选答案
 *   explanation?: string;    // 解析文字（可选）
 * }
 *
 * answers 的含义由 front.type 决定：
 *
 * 1. basic
 *    - answers.length === 1
 *    - answers[0] 是一组“可接受的文本答案”（可以只有一个）
 *      例如： [["声音由物体振动产生。", "声音是由物体振动产生的。"]]
 *
 * 2. single_choice
 *    - answers.length === 1
 *    - answers[0] 是一组“可接受的选项编码”，推荐使用字母：
 *        "A"、"B"、"C"、"D" ...
 *      （编码与 options 数组下标映射：
 *         0 -> "A", 1 -> "B", 2 -> "C", 3 -> "D", ...）
 *    - 旧数据如果使用 "0"、"1" 这样的数字字符串，判题时会自动视为 A/B 等价。
 *
 * 3. multiple_choice
 *    - answers.length === 正确选项个数
 *    - 每个 slot 表示一个正确选项，内部数组为“该选项的候选编码”，推荐只写一个字母：
 *      例如： [["A"], ["C"], ["D"]] 表示 A、C、D 三个选项正确
 *
 * 4. fill_in_blank
 *    - answers.length === 空的数量
 *    - 第 i 个 slot 存放第 i 个空的可接受文本答案
 *      例如： [["物体振动", "物体的振动"], ["真空"]]
 *
 * 旧数据兼容（back，JSON 部分）：
 *   - 如果 back 是合法 JSON 且包含 answers 数组，则直接按 JSON 使用（并做类型过滤）。
 *
 * 旧数据兼容（back，非 JSON 部分，本文件中实现你指定的简化规则）：
 *
 *   当 back 不是合法 JSON 字符串时：
 *
 *   1. 统一换行符为 '\n'，按行切分；
 *   2. 去掉头尾空行；
 *   3. 从第一行开始：
 *      - 直到遇到第一行“完全空白”的行（trim() 为空字符串）之前的所有非空行：
 *          → 每一行作为一个“答案 slot”；
 *          → 行内再按“逗号、中文逗号、分号、中文分号”分割成多个候选答案；
 *            例如： "A,B;C" → ["A","B","C"]
 *      - 遇到第一行空行之后的剩余所有内容（包括中间的空行）：
 *          → 以原始换行合并为 explanation（去掉首尾空白字符）；
 *   4. 如果整个文本在去掉头尾空行后为空：
 *      - 则返回：
 *          answers: [[raw]]
 *          explanation: undefined
 *
 *   该规则对所有题型统一适用（basic / single_choice / multiple_choice / fill_in_blank）。
 */

export type QuestionType =
    | "basic"
    | "single_choice"
    | "multiple_choice"
    | "fill_in_blank";

export interface FrontSchema {
    version: 1;
    type: QuestionType;
    score: number;
    prompt: string;
    options?: string[];
    media?: {
        imageUrl?: string;
        audioUrl?: string;
        videoUrl?: string;
    };
}

export interface BackSchema {
    answers: string[][];
    explanation?: string;
}

export type UserAnswer = string[];

/**
 * 检查某个值是否是合法的 QuestionType。
 */
function isQuestionType(value: unknown): value is QuestionType {
    return (
        value === "basic" ||
        value === "single_choice" ||
        value === "multiple_choice" ||
        value === "fill_in_blank"
    );
}

/**
 * 判断一个 unknown 是否“看起来像” FrontSchema（部分字段）。
 */
function isFrontLike(obj: unknown): obj is Partial<FrontSchema> {
    if (typeof obj !== "object" || obj === null) return false;
    const rec = obj as Record<string, unknown>;
    return isQuestionType(rec.type);
}

/**
 * 将选项下标（0,1,2,3,...) 转换为字母编码（A,B,C,D,...）。
 */
export function indexToLetter(index: number): string {
    return String.fromCharCode(65 + index); // 65 = 'A'
}

/**
 * 将字母编码（A,B,C,D,...) 转回下标（0,1,2,3,...）。
 * 非法输入返回 -1。
 */
export function letterToIndex(letter: string): number {
    if (!letter) return -1;
    const upper = letter.toUpperCase();
    const code = upper.charCodeAt(0);
    if (code < 65 || code > 90) return -1;
    return code - 65;
}

/**
 * 将 choice 的编码（兼容旧数据）规范化为字母编码：
 * - 若是单个字母，如 "a" / "B" → 转成大写 "A" / "B"
 * - 若是数字字符串，如 "0" / "1" → 映射为 "A" / "B"
 * - 其他情况返回 null（用于过滤）
 */
function normalizeChoiceCode(code: string): string | null {
    const trimmed = code.trim();
    if (!trimmed) return null;

    // 数字形式（旧数据："0" -> "A"）
    if (/^\d+$/.test(trimmed)) {
        const idx = Number(trimmed);
        if (!Number.isInteger(idx) || idx < 0) return null;
        return indexToLetter(idx);
    }

    // 单个字母
    if (/^[A-Za-z]$/.test(trimmed)) {
        return trimmed.toUpperCase();
    }

    return null;
}

/**
 * 解析 front 字符串为 FrontSchema。
 *
 * 行为：
 * - 如果 raw 是合法 JSON 且拥有可识别的 type，则按 JSON 使用；
 * - 否则，将 raw 视为 basic 类型的纯文本题干：
 *     {
 *       version: 1,
 *       type: "basic",
 *       score: 1,
 *       prompt: raw
 *     }
 */
export function parseFront(raw: string): FrontSchema {
    let parsed: unknown;

    try {
        parsed = JSON.parse(raw);
    } catch {
        // 非 JSON，fall through 到 basic 默认分支
    }

    if (isFrontLike(parsed)) {
        const rec = parsed as Partial<FrontSchema>;

        const scoreValue =
            typeof rec.score === "number" && !Number.isNaN(rec.score)
                ? rec.score
                : 1;

        const promptValue =
            typeof rec.prompt === "string" ? rec.prompt : "";

        const optionsValue =
            Array.isArray(rec.options) ? rec.options : undefined;

        let mediaValue: FrontSchema["media"] | undefined;
        if (typeof rec.media === "object" && rec.media !== null) {
            const m = rec.media as Record<string, unknown>;
            mediaValue = {
                imageUrl: typeof m.imageUrl === "string" ? m.imageUrl : undefined,
                audioUrl: typeof m.audioUrl === "string" ? m.audioUrl : undefined,
                videoUrl: typeof m.videoUrl === "string" ? m.videoUrl : undefined,
            };
        }

        return {
            version: 1,
            type: rec.type as QuestionType,
            score: scoreValue,
            prompt: promptValue,
            options: optionsValue,
            media: mediaValue,
        };
    }

    // 旧数据：front 是普通字符串，解析为 basic 类型，字段设缺省值
    return {
        version: 1,
        type: "basic",
        score: 1,
        prompt: raw,
    };
}

/**
 * 判断一个 unknown 是否“看起来像” BackSchema（至少包含 answers 数组）。
 */
function isBackLike(obj: unknown): obj is Partial<BackSchema> {
    if (typeof obj !== "object" || obj === null) return false;
    const rec = obj as Record<string, unknown>;
    return Array.isArray(rec.answers);
}

/**
 * 将一行文本拆分为多个候选答案：
 * - 使用英文逗号、中文逗号、英文分号、中文分号作为分隔符
 * - 去掉每个片段的首尾空格
 * - 过滤掉空字符串
 */
function splitCandidates(line: string): string[] {
    return line
        .split(/[;,，；]/)
        .map((part) => part.trim())
        .filter((part) => part.length > 0);
}

/**
 * 解析 back 字符串为 BackSchema。
 *
 * 行为：
 * - 如果 raw 是合法 JSON 且包含 answers 数组，则按 JSON 使用（并做基本过滤）；
 * - 否则，按统一规则解析非 JSON 文本：
 *
 *   1. 统一换行符为 \n，按行切分；
 *   2. 去掉头尾空行；
 *   3. 从第一行开始，直到遇到第一行“完全空白”的行（trim() 为空）之前的所有非空行：
 *        → 每一行作为一个答案 slot；
 *        → 行内再按“逗号/中文逗号/分号/中文分号”切成多个候选；
 *      遇到第一行空行之后的所有内容（包括中间的空行）：
 *        → 合并为 explanation（整体 trim 一次，空则为 undefined）；
 *   4. 若去掉头尾空行后没有任何内容：
 *        → answers: [[raw]]，explanation: undefined
 *
 *   该规则对所有题型统一适用（basic / single_choice / multiple_choice / fill_in_blank）。
 *
 *   no_answer（默认 false）：
 *   - 当传入 true 且 raw 不是合法 JSON 时，跳过上述行解析，直接将 raw 视为 explanation，answers 返回空数组。
 */
export function parseBack(raw: string, no_answer = false): BackSchema {
    let parsed: unknown;

    try {
        parsed = JSON.parse(raw);
    } catch {
        // 非 JSON，fall through 到文本解析分支
    }

    // JSON 情况：直接解析
    if (isBackLike(parsed)) {
        const rec = parsed as Partial<BackSchema>;

        const answersRaw = Array.isArray(rec.answers) ? rec.answers : [];
        const answers: string[][] = answersRaw.map((slot) => {
            if (Array.isArray(slot)) {
                return slot
                    .map((s) => (typeof s === "string" ? s : String(s)))
                    .filter((s) => s.trim().length > 0);
            }
            if (typeof slot === "string") {
                return [slot];
            }
            return [];
        }).filter((slot) => slot.length > 0);

        const explanation =
            typeof rec.explanation === "string" ? rec.explanation : undefined;

        return {
            answers,
            explanation,
        };
    }

    // 非 JSON 情况：按行解析 raw 文本
    if (no_answer) {
        const explanationOnly = raw.replace(/\r\n?/g, "\n").trim();
        return {
            answers: [],
            explanation: explanationOnly || undefined,
        };
    }
    // 统一换行符
    const unified = raw.replace(/\r\n?/g, "\n");
    const allLines = unified.split("\n");

    // 去掉头尾空行
    let start = 0;
    let end = allLines.length;
    while (start < end && allLines[start].trim() === "") start++;
    while (end > start && allLines[end - 1].trim() === "") end--;
    const lines = allLines.slice(start, end);

    // 若去掉头尾空行后完全为空，则退化为 [[raw]]
    if (lines.length === 0) {
        return {
            answers: [[raw]],
        };
    }

    // 寻找第一行“完全空白”的行作为分隔符
    let blankIndex = -1;
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].trim() === "") {
            blankIndex = i;
            break;
        }
    }

    const answerLines =
        blankIndex === -1 ? lines : lines.slice(0, blankIndex);
    const explanationLines =
        blankIndex === -1 ? [] : lines.slice(blankIndex + 1);

    // 每一行作为一个 slot，行内支持逗号/分号分隔多个候选
    const slots: string[][] = [];
    for (const line of answerLines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        const candidates = splitCandidates(trimmed);
        if (candidates.length > 0) {
            slots.push(candidates);
        }
    }

    // 如果没有有效的答案行，则退化为 [[raw]]
    if (slots.length === 0) {
        return {
            answers: [[raw]],
        };
    }

    const explanationText = explanationLines.join("\n").trim();

    return {
        answers: slots,
        explanation: explanationText || undefined,
    };
}

/**
 * 解析填空题题干中的空位数量。
 *
 * 约定：
 * - 填空题的空用 {{1}}、{{2}}、{{3}} ... 表示
 * - 例如："声音由 {{1}} 产生，在 {{2}} 中不能传播。" -> 2 个空
 */
export function countBlanks(prompt: string): number {
    const matches = prompt.match(/\{\{\d+}}/g);
    return matches ? matches.length : 0;
}

/**
 * 将字符串进行简单规范化，便于比较。
 * 当前策略：
 * - 去掉首尾空格
 * - 转为小写
 *
 * 用于 basic / fill_in_blank 等题型答案的文本比较。
 */
function normalizeText(s: string): string {
    return s.trim().toLowerCase();
}

/**
 * 判题函数：根据 front / back / userAnswer 判断是否答对。
 *
 * 约定 userAnswer 格式：
 * - basic:           string
 * - single_choice:   string        (选项字母编码，例如 "A")
 * - multiple_choice: string[]      (选项字母编码数组，例如 ["A","C"])
 * - fill_in_blank:   string[]      (各空的答案，例如 ["物体振动", "真空"])
 *
 * 返回：
 * - true  表示完全正确
 * - false 表示错误或答案格式不合法
 *
 * 说明：
 * - 当前实现采用“全对才得分”的策略，不支持部分得分。
 *   如果需要部分得分，可在此基础上扩展为返回分值或更复杂的结果结构。
 */
export function checkAnswer(
    front: FrontSchema,
    back: BackSchema,
    userAnswer: UserAnswer
): boolean {
    const { type } = front;
    const slots = back.answers; // string[][]

    // userAnswer 现在固定为 string[]
    const ua = Array.isArray(userAnswer) ? userAnswer : [];

    switch (type) {
        // ===== basic: 只看第一项 =====
        case "basic": {
            const userText = ua[0] ?? "";
            const candidates = slots[0] ?? [];
            if (candidates.length === 0) return false;

            const normUser = normalizeText(userText);

            return candidates.some(
                (c) => normalizeText(c) === normUser
            );
        }

        // ===== single_choice: 只看第一项（例如 ["A"]） =====
        case "single_choice": {
            const choice = ua[0] ?? "";
            const normCode = normalizeChoiceCode(choice);
            if (!normCode) return false;

            const candidates = slots[0] ?? [];
            const normalizedCandidates = candidates
                .map((c) => normalizeChoiceCode(c))
                .filter((x): x is string => x !== null);

            return normalizedCandidates.includes(normCode);
        }

        // ===== multiple_choice: ua 为 ["A", "C"] 这样的数组 =====
        case "multiple_choice": {
            // 用户答案的有效编码
            const userCodes = ua
                .map((x) => normalizeChoiceCode(x))
                .filter((x): x is string => x !== null);

            // 如果有非法编码（null 被过滤掉后长度不一致），视为错误
            if (userCodes.length !== ua.length) return false;

            // 正确答案：所有 slot 展开的编码
            const correctCodes = slots
                .flat()
                .map((c) => normalizeChoiceCode(c))
                .filter((x): x is string => x !== null);

            if (correctCodes.length === 0) return false;

            // 数量必须相同（多选必须完全匹配）
            if (correctCodes.length !== userCodes.length) return false;

            // 集合比较（忽略顺序）
            const sortedUser = [...userCodes].sort();
            const sortedCorrect = [...correctCodes].sort();

            return sortedCorrect.every((c, i) => c === sortedUser[i]);
        }

        // ===== fill_in_blank: ua=["答案1","答案2",...]，与 slots 一一对应 =====
        case "fill_in_blank": {
            const blankCount = countBlanks(front.prompt);
            let slotList = slots;

            // 特殊情况：blankCount > 1 但 slots 只有一组答案，
            // 将该组内的每个元素视为对应空位的答案
            if (blankCount > 1 && slots.length === 1) {
                const flat = slots[0] ?? [];
                slotList = flat.map((ans) => [ans]);
            }

            // 必须一一对应
            if (blankCount !== slotList.length) return false;
            if (ua.length !== blankCount) return false;

            for (let i = 0; i < blankCount; i++) {
                const candidates = slotList[i] ?? []; // 当前空允许的多个答案
                const answerText = ua[i] ?? "";

                const normUser = normalizeText(answerText);

                const matched = candidates.some(
                    (c) => normalizeText(c) === normUser
                );

                if (!matched) return false;
            }

            return true;
        }

        default:
            return false;
    }
}
