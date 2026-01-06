import type { SupabaseClient } from "@supabase/supabase-js";

export function easeFactorToColor(easeFactor: number | null | undefined): string {
    if (!easeFactor) return "bg-neutral-500";
    if (easeFactor < 1.5) return "bg-purple-700";
    if (easeFactor < 2.5) return "bg-orange-500";
    if (easeFactor < 3.5) return "bg-blue-500";
    return "bg-green-600";
}

export function easeFactorFromLevel(level: number): number {
    const easeMap: Record<number, number> = {
        1: 1.0,
        2: 2.0,
        3: 3.0,
        4: 4.0,
    };
    return easeMap[level] ?? 2.0;
}

export type CardStatsSnapshot = {
    card_id: string;
    review_count: number;
    correct_count: number;
    wrong_count: number;
    ease_factor: number;
    last_reviewed_at: string;
};

type RecordDifficultyParams = {
    supabase: SupabaseClient;
    userId: string;
    cardId: string;
    deckId?: string | null;
    easeFactor: number;
    reviewedAt: string;
    timeSpentSeconds: number | null;
    isQuestion: boolean;
    meta?: Record<string, unknown>;
};

export async function recordDifficultyUpdate(params: RecordDifficultyParams): Promise<CardStatsSnapshot | null> {
    const {
        supabase,
        userId,
        cardId,
        deckId,
        easeFactor,
        reviewedAt,
        timeSpentSeconds,
        isQuestion,
        meta,
    } = params;
    const isCorrect = easeFactor > 2;

    await supabase.from("card_reviews").insert({
        card_id: cardId,
        reviewed_at: reviewedAt,
        user_answer: null,
        is_correct: isCorrect,
        time_spent: timeSpentSeconds,
        belongs_to: deckId ?? null,
        is_question: isQuestion,
        meta: meta ?? { difficulty: easeFactor },
    });

    const { data: existing, error } = await supabase
        .from("card_stats")
        .select("id, review_count, correct_count, wrong_count")
        .eq("user_id", userId)
        .eq("card_id", cardId)
        .maybeSingle();

    if (error) {
        console.error("recordDifficultyUpdate card_stats error", error);
        return null;
    }

    if (!existing) {
        await supabase.from("card_stats").insert({
            user_id: userId,
            card_id: cardId,
            review_count: 1,
            correct_count: isCorrect ? 1 : 0,
            wrong_count: isCorrect ? 0 : 1,
            ease_factor: easeFactor,
            last_reviewed_at: reviewedAt,
        });
        return {
            card_id: cardId,
            review_count: 1,
            correct_count: isCorrect ? 1 : 0,
            wrong_count: isCorrect ? 0 : 1,
            ease_factor: easeFactor,
            last_reviewed_at: reviewedAt,
        };
    }

    const newReviewCount = (existing.review_count || 0) + 1;
    const newCorrectCount = isCorrect ? ((existing.correct_count || 0) + 1) : 0;
    const newWrongCount = isCorrect ? 0 : ((existing.wrong_count || 0) + 1);

    await supabase
        .from("card_stats")
        .update({
            review_count: newReviewCount,
            correct_count: newCorrectCount,
            wrong_count: newWrongCount,
            ease_factor: easeFactor,
            last_reviewed_at: reviewedAt,
        })
        .eq("id", existing.id);

    return {
        card_id: cardId,
        review_count: newReviewCount,
        correct_count: newCorrectCount,
        wrong_count: newWrongCount,
        ease_factor: easeFactor,
        last_reviewed_at: reviewedAt,
    };
}
