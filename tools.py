from dotenv import load_dotenv
from supabase import create_client
import os
import json
load_dotenv()

url = os.getenv("url")
key = os.getenv("key")
supabase = create_client(url, key)

def query_database(sql: str) -> str:
    """
    Query the PC components database to get prices, benchmarks and compatibility info.
    Args:
        sql: SQL SELECT query to execute (no semicolons).
    """
    try:
        clean_sql = sql.strip().rstrip(";")
        response = supabase.rpc("run_query", {"sql": clean_sql}).execute()
        return json.dumps(response.data, ensure_ascii=False, indent=2) if response.data else "[]"
    except Exception as e:
        return f"Database Error: {e}"


def get_cpu_mb(min_p, max_p, ddr):
        tmp_sql = f"""
            WITH cpu_x_test_prices AS (
              SELECT
                c.normalized_model_name,
                t.test, t.result,
                p.price_rub,
                p.source_url,
                c.tdp,
                CASE 
                    WHEN c.tdp < 70 THEN 'low'
                    WHEN c.tdp >= 70 AND c.tdp < 121 THEN 'mid'
                    ELSE 'high'
                END AS tdp_tier,
                c.socket,
                c.compatible_chipsets_no_bios_flash
              FROM cpu_x_test AS t
              INNER JOIN cpus AS c ON c.id = t.cpu_id
              INNER JOIN component_prices AS p 
                  ON c.id = p.component_id 
                 AND p.is_available = TRUE 
                 AND p.is_verified = TRUE
            ),
            motherboard_prices AS (
              SELECT
                m.normalized_name,
                m.socket,
                m.chipset,
                m.vrm_tier,
                m.form_factor,
                m.ram_type,
                m.num_ram_slots,
                m.cpu_power_pins,
                m.required_cpu_power_pins,
                p.price_rub AS mb_price,
                p.source_url
              FROM motherboards AS m
              INNER JOIN component_prices AS p 
                  ON m.id = p.component_id 
                 AND p.is_available = TRUE 
                 AND p.is_verified = TRUE
            )
            SELECT 
              c.normalized_model_name AS cpu_name,
              m.normalized_name AS motherboard_name,
              c.test,
              c.result,
              c.price_rub + m.mb_price AS cpu_and_mb_price,
              c.tdp,
              m.form_factor,
              m.ram_type,
              m.num_ram_slots,
              m.cpu_power_pins,
              m.required_cpu_power_pins,
              m.source_url as motherboard_url,
              c.source_url as cpu_url
            FROM cpu_x_test_prices AS c
            INNER JOIN motherboard_prices AS m 
                ON c.socket = m.socket
               AND m.chipset = ANY(c.compatible_chipsets_no_bios_flash)
               AND m.vrm_tier = c.tdp_tier
               AND m.ram_type = '{ddr}'
            WHERE (c.price_rub + m.mb_price) BETWEEN {min_p} AND {max_p}
            ORDER BY (c.price_rub + m.mb_price), cpu_name, motherboard_name, test
            """
        tmp_resp = supabase.rpc("run_query", {"sql": tmp_sql}).execute()
        return tmp_resp.data


def get_gpu(min_p, max_p, task, res):
    if task == "AI":
        tmp_sql = f"""
        SELECT 
            g.normalized_name, g.tdp, g.length_mm, g.power_connectors, 
            p.source_url, p.price_rub, m.vram_gb
        FROM gpus as g
        INNER JOIN component_prices as p ON p.component_id = g.id
            AND p.is_available = TRUE 
            AND p.is_verified = TRUE
            AND p.price_rub BETWEEN {min_p} AND {max_p}
        INNER JOIN model_name as m ON m.model_id = g.model_id AND g.normalized_name LIKE '%RTX%' 
        ORDER BY m.vram_gb, p.price_rub
        LIMIT 20000
        """
    else:
        cnt_sql = (
            f"SELECT COUNT(*) FROM gpus g "
            f"INNER JOIN component_prices p ON p.component_id = g.id "
            f"AND p.is_available=TRUE AND p.is_verified=TRUE "
            f"AND p.price_rub BETWEEN {min_p} AND {max_p} "
            f"INNER JOIN model_x_test mxt ON mxt.model_id = g.model_id "
            f"AND mxt.test='{task}' AND mxt.resolution={res}"
        )
        cnt_resp = supabase.rpc("run_query", {"sql": cnt_sql}).execute()
        if not cnt_resp.data or cnt_resp.data[0].get("count", 0) == 0:
            task = "Relative Performance TechPowerUp"

        tmp_sql = f"""
            SELECT normalized_name, tdp, length_mm, power_connectors, result, 1000*result/price_rub as result_per_price, max_result, price_rub, source_url
            FROM (
                SELECT 
                    g.*, p.price_rub, p.source_url, mxt.test, mxt.result, MAX(mxt.result) OVER (PARTITION BY mxt.test) as max_result
                    FROM gpus as g
                    INNER JOIN component_prices as p 
                        ON p.component_id = g.id
                        AND p.is_available = TRUE 
                        AND p.is_verified = TRUE
                        AND p.price_rub BETWEEN {min_p} AND {max_p}
                    INNER JOIN model_x_test as mxt 
                        ON mxt.model_id = g.model_id 
                        AND mxt.test = '{task}'
                        AND mxt.resolution = {res}
                    ) t
            WHERE result >= 0.85 * max_result
            ORDER BY result_per_price DESC
            LIMIT 8000
            """

    tmp_resp = supabase.rpc("run_query", {"sql": tmp_sql}).execute()
    return tmp_resp.data

