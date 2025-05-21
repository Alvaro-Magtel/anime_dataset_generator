"""Main execution pipeline for genetic rule mining."""

import ast
import math
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from genetic_rule_miner.config import DBConfig
from genetic_rule_miner.data.database import DatabaseManager
from genetic_rule_miner.data.manager import DataManager
from genetic_rule_miner.models.genetic import GeneticRuleMiner
from genetic_rule_miner.utils.logging import LogManager

LogManager.configure()
logger = LogManager.get_logger(__name__)


def convert_text_to_list_column(df, column_name):
    """
    Convierte una columna que contiene strings representando listas
    en una lista real de Python. Si el valor no es una lista válida,
    la convierte en lista con un solo elemento.
    """

    def parse_cell(x):
        try:
            # Si es string y comienza con '[', intenta parsear
            if isinstance(x, str) and x.startswith("["):
                parsed = ast.literal_eval(x)
                if isinstance(parsed, list):
                    # Limpiar elementos vacíos o espacios
                    return [str(i).strip() for i in parsed if str(i).strip()]
                else:
                    return [str(parsed).strip()]
            elif isinstance(x, str):
                # No es lista, pero es string: lo convierte en lista de un elemento
                return [x.strip()] if x.strip() else []
            elif isinstance(x, list):
                # Ya es lista
                return [str(i).strip() for i in x if str(i).strip()]
            else:
                # Cualquier otro tipo, convertir a str y poner en lista
                return [str(x).strip()] if x else []
        except Exception as e:
            logger.warning(
                f"Error parsing column {column_name} value '{x}': {e}"
            )
            return []

    df[column_name] = df[column_name].fillna("[]").apply(parse_cell)


def main() -> None:
    """Execute the complete rule mining pipeline."""
    try:
        logger.info("Starting rule mining pipeline")

        # Initialize components
        db_config = DBConfig()
        data_manager = DataManager(db_config)

        # Data loading and preparation
        logger.info("Loading and preprocessing data...")
        user_details, anime_data, user_scores = (
            data_manager.load_and_preprocess_data()
        )
        # Remove 'rating' column from user_scores if it exists
        if "rating" in user_scores.columns:
            user_scores = user_scores.drop(columns=["rating"])

        logger.info("Merging preprocessed data...")
        merged_data = DataManager.merge_data(
            user_scores, user_details, anime_data
        )

        # Clean merged_data
        if "rating" in merged_data.columns:
            logger.info("Dropping rows with unknown ratings...")
            merged_data = merged_data[merged_data["rating"] != "unknown"]

        logger.info("Dropping unnecessary columns...")
        merged_data = merged_data.drop(
            columns=["username", "name", "mal_id", "user_id"], errors="ignore"
        )

        # Convert text columns to list columns
        for col in ["producers", "genres", "keywords"]:
            if col in merged_data.columns:
                logger.info(f"Converting column '{col}' from text to list...")
                convert_text_to_list_column(merged_data, col)

        logger.info("Starting evolution process...")

        # Para almacenar reglas finales
        all_rules = []

        batch_size = 6
        targets = list(merged_data["anime_id"].unique())
        logger.info(
            f"Total targets to process: {len(targets)}. Batch size: {batch_size}."
        )
        total_batches = math.ceil(
            len(targets) / batch_size
        )  # Redondea hacia arriba
        start_time = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as executor:
            for batch_num in range(total_batches):
                batch_targets = targets[
                    batch_num * batch_size : (batch_num + 1) * batch_size
                ]

                future_to_id = {
                    executor.submit(
                        GeneticRuleMiner(
                            df=merged_data,
                            target_column="anime_id",
                            user_cols=user_details.columns.tolist(),
                            pop_size=720,
                            generations=10000,
                        ).evolve_per_target,
                        target_id,
                    ): target_id
                    for target_id in batch_targets
                }

                try:
                    for future in as_completed(future_to_id):
                        tid = future_to_id[future]
                        try:
                            result = future.result()
                            all_rules.extend(result)
                            logger.info(
                                f"Target {tid} finished with {len(result)} rules."
                            )
                        except Exception as exc:
                            logger.error(
                                f"Target {tid} generated an exception: {type(exc).__name__}: {exc}"
                            )
                            logger.error(traceback.format_exc())
                except KeyboardInterrupt:
                    logger.warning("Proceso interrumpido por usuario (Ctrl+C)")
                    for future in future_to_id:
                        future.cancel()
                    return

                logger.info(
                    f"Batch {batch_num + 1}/{total_batches} completed."
                )
        duration = time.perf_counter() - start_time
        logger.info(f"Evolution process completed in {duration:.4f} seconds.")
        # Guardar reglas si existen
        if all_rules:
            db_manager = DatabaseManager(config=db_config)
            db_manager.save_rules(all_rules)

    except Exception as e:
        logger.error("Pipeline failed: %s", str(e), exc_info=True)
        raise


if __name__ == "__main__":
    main()
