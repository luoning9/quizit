// src/lib/supabaseClient.ts
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!supabaseUrl || !supabaseAnonKey) {
    // 方便调试：环境变量没配置好时在控制台报个错
    // 以后可以删掉
    console.error('Supabase URL 或 Anon Key 未配置，请检查 .env.local');
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);