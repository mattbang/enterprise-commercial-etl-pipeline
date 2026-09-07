"""Production-reference orchestrator.

This module documents the private deployment path and requires integration
modules that are intentionally excluded from the public portfolio. Run
``python demo.py`` for the supported, self-contained demonstration.
"""

import logging
import sys
import os
# Silence TensorFlow logs (must be before importing libraries that use TF/Selenium)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import time
from pathlib import Path

# Add project root to sys.path
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

# Import helpers
from integration.qlik_downloads import run_crm_pipeline as run_downloads_and_pipeline
from integration.helpers.reload_helpers import reload_all_apps
from integration.helpers.validation_helpers import validate_all
from integration.helpers.SendEmail import send_email
from integration.helpers.forecast_quality import build_unconventional_qa_report, generate_controller_drafts
import shutil
from core.error_handling import PipelineErrorHandler
from core.path_resolver import get_config_path, resolve_config
from core.publication_control import (
    BlockingValidationError,
    RunStatus,
    exit_code_for,
    load_fresh_validation_report,
    missing_or_stale_files,
    terminal_status,
    validation_result_failures,
)


# AI Context Logging
try:
    from core.ai_logger import ai_log_clear, ai_log_summary
except ImportError:
    ai_log_clear = lambda: None
    ai_log_summary = lambda: {}

# Configure logging — explicit setup (immune to basicConfig import-order races)
_root = logging.getLogger()
_root.setLevel(logging.INFO)
# Remove any handlers added by imported modules' basicConfig calls
_root.handlers.clear()
_fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
_sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
_sh.setFormatter(_fmt)
_log_file = Path(__file__).resolve().parent / "orchestrator.log"
_fh = logging.FileHandler(str(_log_file), mode='w', encoding='utf-8')
_fh.setFormatter(_fmt)
_root.addHandler(_sh)
_root.addHandler(_fh)

# Attach Error Handler to capture warnings/errors
error_handler = PipelineErrorHandler()
error_handler.setLevel(logging.WARNING)
logging.getLogger().addHandler(error_handler)

log = logging.getLogger("Orchestrator")

def load_config():
    """Load configuration through the central placeholder/path resolver."""
    return resolve_config(force_reload=True)

import argparse

def main(argv=None):
    log.info("Orchestrator process started (PID: %d)", os.getpid())

    parser = argparse.ArgumentParser(description="Orchestrate Qlik Datasets Update")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without downloading, reloading, or emailing.")
    parser.add_argument("--skip-downloads", action="store_true", help="Skip the download step but run pipeline, reload, and validation.")
    args = parser.parse_args(argv)

    dry_run = args.dry_run
    skip_downloads = args.skip_downloads

    try:
        config = load_config()
    except Exception as e:
        log.critical("FATAL: Failed during startup/config load: %s", e, exc_info=True)
        return exit_code_for(RunStatus.FAILED)

    try:
        log.info("="*60)
        log.info("STARTING MASTER UPDATE ORCHESTRATION")
        if dry_run:
            log.info("[DRY RUN MODE ENABLED]")
        if skip_downloads:
            log.info("[SKIP DOWNLOADS ENABLED]")
        log.info("="*60)

        # Clear AI context log for fresh run
        ai_log_clear()

        summary_report = []
        errors = []
        verification_complete = True

        # Paths for verification files (from YAML)
        dest_verification_dir = current_dir / "data" / "out"
        src_verification_dir = (
            dest_verification_dir
            if dry_run
            else get_config_path("outputs", "qvd_target_dir", config=config)
        )

        # --- STEP 1: DOWNLOADS & PIPELINE ---
        log.info("\n>>> STEP 1: DOWNLOADS & DATA PIPELINE")
        t0 = time.time()
        try:
            if run_downloads_and_pipeline(dry_run=dry_run, skip_downloads=skip_downloads):
                msg = "✅ Downloads & Pipeline: SUCCESS"
                log.info(msg)
                summary_report.append(msg)
            else:
                msg = "❌ Downloads & Pipeline: FAILED"
                log.error(msg)
                summary_report.append(msg)
                errors.append("Pipeline execution failed. Check orchestrator.log for details.")
                send_summary_email(
                    summary_report,
                    errors,
                    dry_run=dry_run,
                    config=config,
                    status=RunStatus.FAILED,
                )
                return exit_code_for(RunStatus.FAILED)
        except Exception as e:
            msg = f"❌ Downloads & Pipeline: EXCEPTION ({e})"
            log.error(msg, exc_info=True)
            errors.append(msg)
            send_summary_email(
                summary_report,
                errors,
                dry_run=dry_run,
                config=config,
                status=RunStatus.FAILED,
            )
            return exit_code_for(RunStatus.FAILED)

        log.info(f"Step 1 finished in {time.time()-t0:.1f}s")

        # --- STEP 1.5: BLOCKING PRE-PUBLICATION READINESS ---
        log.info("\n>>> STEP 1.5: BLOCKING PRE-PUBLICATION VALIDATION")
        data_in_dir = current_dir / "data" / "in"
        data_out_dir = current_dir / "data" / "out"
        candidate_dataset = data_out_dir / "MarketData_ASP_&_MS_Final_python.csv"
        qa_report_path = data_out_dir / "MarketData_QA_report.json"

        try:
            if dry_run:
                log.info("[DRY RUN] Pre-publication artifact checks simulated.")
            else:
                load_fresh_validation_report(qa_report_path, not_before=t0)
                rejected = missing_or_stale_files([candidate_dataset], not_before=t0)
                if rejected:
                    raise BlockingValidationError(
                        "Candidate dataset is missing, empty, or stale: "
                        + ", ".join(str(path) for path in rejected)
                    )
            msg = "Pre-publication validation: PASSED"
            log.info(msg)
            summary_report.append(msg)
        except Exception as e:
            msg = f"Pre-publication validation: FAILED ({e})"
            log.error(msg, exc_info=True)
            errors.append(msg)
            send_summary_email(
                summary_report,
                errors,
                dry_run=dry_run,
                config=config,
                status=RunStatus.FAILED,
            )
            return exit_code_for(RunStatus.FAILED)

        # --- STEP 2: RELOAD QLIK APPS ---
        log.info("\n>>> STEP 2: RELOAD QLIK APPS")
        t0 = time.time()
        reload_start_time = t0 # Capture start time to check for stale files later
        try:
            results = reload_all_apps(dry_run=dry_run, config=config)
            for app, success in results.items():
                status = "SUCCESS" if success else "FAILED"
                icon = "✅" if success else "❌"
                msg = f"{icon} Reload {app}: {status}"
                log.info(msg)
                summary_report.append(msg)
                if not success:
                    errors.append(f"Failed to reload app: {app}")
        except Exception as e:
            msg = f"❌ Reload Apps: EXCEPTION ({e})"
            log.error(msg, exc_info=True)
            errors.append(msg)

        log.info(f"Step 2 finished in {time.time()-t0:.1f}s")

        if errors:
            send_summary_email(
                summary_report,
                errors,
                dry_run=dry_run,
                config=config,
                status=RunStatus.FAILED,
            )
            return exit_code_for(RunStatus.FAILED)

        # Wait for reloads to process on server BEFORE collecting verification files
        # The reload_app function just TRIGGERS it. It doesn't wait for completion.
        wait_time = config["orchestration"]["timeouts"]["reload_wait_seconds"]

        if dry_run:
            log.info(f"[DRY RUN] Skipping {wait_time}s wait time.")
        else:
            log.info(f"Waiting {wait_time} seconds for reloads to complete on server...")
            time.sleep(wait_time)

        # --- STEP 2.5: COLLECT VERIFICATION FILES ---
        # Now that we've waited, the files on OneDrive/Qlik should be fresh.
        log.info("\n>>> STEP 2.5: COLLECT VERIFICATION FILES")

        # Define polling parameters
        poll_timeout = config["orchestration"]["timeouts"]["poll_timeout_seconds"]
        poll_interval = config["orchestration"]["timeouts"]["poll_interval_seconds"]

        # Files we expect from the Addressable app ONLY (deprecated apps removed)
        expected_verification_files = [
            "MarketData_Add_Final_Qlik_Verified.csv",  # ASP & MS Overview Addressable
        ]

        try:
            if dry_run:
                 log.info("[DRY RUN] Would poll for fresh files in OneDrive and copy to data/out.")
                 summary_report.append("✅ Verification File Collection: SUCCESS (SIMULATED)")
            else:
                dest_verification_dir.mkdir(parents=True, exist_ok=True)
                log.info(f"Polling for fresh verification files directly from Source: {src_verification_dir}")

                start_poll = time.time()
                copied_files = set()

                while time.time() - start_poll < poll_timeout:
                    for fname in expected_verification_files:
                        csv_file = src_verification_dir / fname
                        if csv_file.exists() and fname not in copied_files:
                            try:
                                if csv_file.stat().st_mtime >= reload_start_time:
                                    log.info(f"Found FRESH file: {fname} (Modified: {time.ctime(csv_file.stat().st_mtime)})")
                                    shutil.copy2(csv_file, dest_verification_dir / fname)
                                    copied_files.add(fname)
                            except Exception as e:
                                log.warning(f"Could not check timestamp for {fname}: {e}")

                    # All expected files found?
                    if len(copied_files) >= len(expected_verification_files):
                        log.info("All expected verification files collected.")
                        break

                    time.sleep(poll_interval)

                # Final status
                log.info("Polling finished. Performing final collection pass...")

                count_fresh = len(copied_files)
                count_missing = 0

                for fname in expected_verification_files:
                    csv_file = src_verification_dir / fname
                    if fname not in copied_files:
                        if csv_file.exists():
                            file_age = time.time() - csv_file.stat().st_mtime
                            log.warning(
                                f"[UNVERIFIED] File {fname} was not refreshed this run "
                                f"(Age: {file_age/60:.1f} min); stale evidence was not copied."
                            )
                            count_missing += 1
                        else:
                            log.warning(f"[UNVERIFIED] Expected file {fname} was not found")
                            count_missing += 1

                verification_complete = count_missing == 0
                state = "SUCCESS" if verification_complete else "UNVERIFIED"
                msg = (
                    f"Verification File Collection: {state} "
                    f"({count_fresh} fresh, {count_missing} missing or stale)"
                )
                log.info(msg)
                summary_report.append(msg)

        except Exception as e:
            verification_complete = False
            msg = f"Verification File Collection: UNVERIFIED ({e})"
            log.warning(msg, exc_info=True)
            summary_report.append(msg)

        if not verification_complete:
            status = RunStatus.UNVERIFIED
            summary_report.append(
                "Run status: UNVERIFIED - dashboard freshness could not be proven."
            )
            send_summary_email(
                summary_report,
                errors,
                dry_run=dry_run,
                config=config,
                status=status,
            )
            log.warning("ORCHESTRATION UNVERIFIED")
            return exit_code_for(status)

        # --- STEP 3: VALIDATION ---
        log.info("\n>>> STEP 3: VALIDATION CHECKS")
        t0 = time.time()
        try:
            val_results = validate_all(str(data_in_dir), str(data_out_dir), dry_run=dry_run, config=config)
            errors.extend(validation_result_failures(val_results))
            for check, res in val_results.items():
                status = "PASSED" if res["pass"] else "FAILED"
                icon = "✅" if res["pass"] else "❌"
                # Include the message in the log line so user sees "QA Doc Generated: 5 issues flagged" even on PASS
                msg = f"{icon} {check}: {status} | {res.get('msg')}"
                log.info(msg)
                summary_report.append(msg)
                if not res["pass"]:
                    # Append detail logs to summary if failed
                    summary_report.append(f"<pre>{res.get('msg')}</pre>")

        except Exception as e:
            msg = f"❌ Validation: EXCEPTION ({e})"
            log.error(msg, exc_info=True)
            errors.append(msg)

        log.info(f"Step 3 finished in {time.time()-t0:.1f}s")

        # --- STEP 3.5: FORECAST QUALITY REPORTS ---
        log.info("\n>>> STEP 3.5: FORECAST QUALITY REPORTS")
        qa_attachments = []
        try:
            # Unconventional QA
            unc_path, unc_flags = build_unconventional_qa_report(data_in_dir, data_out_dir)
            msg = f"📊 Unconventional QA: {unc_flags} flags"
            log.info(msg)
            summary_report.append(msg)
            qa_attachments.append(str(unc_path))

            # RedBull QA (already generated by redbull_integration.py in Step 1)
            rb_qa = data_out_dir / "QA_Forecast_Plausibility.csv"
            if rb_qa.exists():
                import pandas as _pd
                _rb_df = _pd.read_csv(rb_qa)
                _rb_flags = int(_rb_df.get("flag_any", _pd.Series(dtype=bool)).sum()) if "flag_any" in _rb_df.columns else 0
                msg = f"📊 RedBull QA: {_rb_flags} flags (per-version)"
                log.info(msg)
                summary_report.append(msg)
                qa_attachments.append(str(rb_qa))
            # Controller email drafts (per-country HTML)
            drafts_dir, draft_countries = generate_controller_drafts(data_out_dir)
            if draft_countries:
                msg = f"📧 Controller drafts generated for: {', '.join(draft_countries)}"
                log.info(msg)
                summary_report.append(msg)
                # Attach each HTML draft
                for html_file in sorted(drafts_dir.glob("*.html")):
                    qa_attachments.append(str(html_file))
        except Exception as e:
            log.warning("Forecast quality reports failed: %s", e)

        # --- STEP 4: TERMINAL STATUS & NOTIFICATION ---
        status = terminal_status(
            failures=errors,
            verification_complete=verification_complete,
        )
        summary_report.append(f"Run status: {status.value}")
        notification_sent = send_summary_email(
            summary_report,
            errors,
            dry_run=dry_run,
            config=config,
            attachments=qa_attachments,
            status=status,
        )
        if not notification_sent and not dry_run:
            errors.append("Summary notification could not be delivered.")
            status = RunStatus.FAILED
        # --- AI CONTEXT SUMMARY ---
        ai_summary = ai_log_summary()
        if ai_summary.get("total_events", 0) > 0:
            log.info("\n>>> AI CONTEXT SUMMARY")
            log.info(f"Total events logged: {ai_summary['total_events']}")
            if ai_summary.get("unmapped_products"):
                log.warning(f"Unmapped products: {ai_summary['unmapped_products']}")
            if ai_summary.get("unmapped_territories"):
                log.warning(f"Unmapped territories: {ai_summary['unmapped_territories']}")
            if ai_summary.get("zero_units_cases"):
                log.warning(f"Zero unit cases: {ai_summary['zero_units_cases']}")

        log.info("="*60)
        log.info("ORCHESTRATION %s", status.value)
        log.info("="*60)
        return exit_code_for(status)
    except SystemExit:
        raise
    except Exception as e:
        log.critical("FATAL: Unhandled exception in orchestration: %s", e, exc_info=True)
        return exit_code_for(RunStatus.FAILED)
    finally:
        logging.shutdown()

def send_summary_email(
    report_lines,
    error_list,
    dry_run=False,
    config=None,
    attachments=None,
    status=None,
):
    """Sends the final status email with optional QA report attachments."""

    # Placeholder recipient used only when no private config is provided.
    recipient = config["email"]["recipient"] if config else "alerts@example.invalid"

    status = status or terminal_status(failures=error_list)

    if status is RunStatus.FAILED:
        subject = "❌ [FAILED] Qlik Update Orchestration"
        color = "red"
        status_text = "The update process encountered errors."
    elif status is RunStatus.UNVERIFIED:
        subject = "⚠️ [UNVERIFIED] Qlik Update Orchestration"
        color = "orange"
        status_text = "The update ran, but current dashboard evidence was not available."
    elif error_handler.has_warnings():
        subject = "⚠️ [WARNING] Qlik Update Orchestration (Issues Found)"
        color = "orange"
        status_text = "The update process completed with warnings."
    else:
        subject = "✅ [SUCCESS] Qlik Update Orchestration"
        color = "green"
        status_text = "The update process completed successfully."

    body_html = f"""
    <h2>Orchestration Status: <span style="color:{color}">{status_text}</span></h2>
    <h3>Summary:</h3>
    <ul>
    """
    for line in report_lines:
        body_html += f"<li>{line}</li>"
    body_html += "</ul>"

    if error_list:
        body_html += "<h3>Errors:</h3><ul>"
        for err in error_list:
            body_html += f"<li style='color:red'>{err}</li>"
        body_html += "</ul>"

    # Add accumulation summary
    summary_text = error_handler.get_summary_text()
    if "No warnings or errors" not in summary_text:
        body_html += "<h3>Pipeline Issues Log:</h3><pre style='background-color:#f8f8f8; padding:10px; border:1px solid #ddd;'>"
        body_html += summary_text
        body_html += "</pre>"

    try:
        send_email(subject, body_html, recipient, dry_run=dry_run, attachments=attachments)
        log.info(f"Sent summary email to {recipient}")
        return True
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        return False

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("FATAL: Orchestrator crashed")
        raise SystemExit(exit_code_for(RunStatus.FAILED))
