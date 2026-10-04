# Test matrix

How the test plan in the project brief (section 28) is covered, and what is **not** covered by automated tests.
Every test named here is checked to exist by `tests/test_docs.py`, so this file cannot drift from the suite.

Run everything with `python -m pytest -q`. Most automated tests drive the real Flask app through its HTTP interface
against an in-memory database; blockchain tests use a real EVM (eth-tester) with the real compiled contract.

## Authentication

| Brief item | Tests |
|---|---|
| Registration | `tests/test_auth.py::test_register_success_hashes_password`, `tests/test_auth.py::test_register_email_normalised_and_duplicate_rejected`, `tests/test_auth.py::test_register_weak_password_and_mismatch`, `tests/test_auth.py::test_register_bad_phone_and_email`, `tests/test_auth.py::test_register_cannot_choose_admin_role` |
| Login | `tests/test_auth.py::test_login_logout_flow`, `tests/test_auth.py::test_login_failures_share_one_message`, `tests/test_auth.py::test_inactive_user_cannot_login`, `tests/test_security.py::test_five_failures_lock_that_client_out_of_that_account` |
| Logout | `tests/test_auth.py::test_logout_requires_post`, `tests/test_security.py::test_logout_really_ends_the_session` |
| Password reset | `tests/test_auth.py::test_reset_token_flow_is_single_use`, `tests/test_auth.py::test_reset_token_tampered_or_expired`, `tests/test_auth.py::test_forgot_password_is_enumeration_safe`, `tests/test_notifications.py::test_forgot_password_emails_a_working_link` |
| Unauthorized access | `tests/test_auth.py::test_anonymous_redirected_from_portals`, `tests/test_auth.py::test_roles_are_isolated`, `tests/test_security.py::test_every_non_public_route_refuses_anonymous_visitors`, `tests/test_security.py::test_each_area_refuses_every_other_role` |

## Seller

| Brief item | Tests |
|---|---|
| Product creation | `tests/test_seller.py::test_create_product_success`, `tests/test_seller.py::test_create_validation`, `tests/test_seller.py::test_create_requires_image` |
| Product editing | `tests/test_seller.py::test_edit_updates_and_resubmits_approved_listing`, `tests/test_seller.py::test_cannot_edit_or_delete_after_auction_starts`, `tests/test_seller.py::test_cannot_touch_another_sellers_product` |
| Product deletion | `tests/test_seller.py::test_delete_removes_product_auction_and_files`, `tests/test_seller.py::test_delete_requires_post` |
| Image upload | `tests/test_seller.py::test_upload_rejects_non_image_with_image_extension`, `tests/test_seller.py::test_edit_image_add_and_remove`, `tests/test_security.py::test_dangerous_or_fake_uploads_are_rejected` |
| Auction creation | `tests/test_seller.py::test_auction_time_rules`, `tests/test_admin.py::test_approve_creates_auction_and_notifies` |

## Buyer

| Brief item | Tests |
|---|---|
| Product search | `tests/test_buyer.py::test_search_title_description_category_and_all_words`, `tests/test_buyer.py::test_search_is_safe_against_wildcards_and_injection` |
| Filtering | `tests/test_buyer.py::test_category_filter`, `tests/test_buyer.py::test_price_filter_uses_current_bid`, `tests/test_buyer.py::test_status_filter`, `tests/test_buyer.py::test_sorting` |
| Bid placement | `tests/test_auction.py::test_first_bid_may_equal_starting_price`, `tests/test_auction.py::test_http_bid_success_json`, `tests/test_auction.py::test_live_bid_reaches_other_viewers` |
| Watchlist | `tests/test_buyer.py::test_watchlist_toggle_and_page`, `tests/test_buyer.py::test_watchlist_is_per_user_and_buyers_only` |
| Reviews | `tests/test_reviews.py::test_paying_buyer_can_review_once_and_it_shows_on_the_page`, `tests/test_reviews.py::test_unpaid_buyers_cannot_review`, `tests/test_reviews.py::test_admin_hides_a_review_and_everything_follows` |

## Auction

| Brief item | Tests |
|---|---|
| Valid bid | `tests/test_auction.py::test_first_bid_may_equal_starting_price`, `tests/test_auction.py::test_bid_updates_state_and_notifies` |
| Invalid bid | `tests/test_auction.py::test_invalid_amounts_rejected`, `tests/test_auction.py::test_bids_refused_unless_active`, `tests/test_auction.py::test_bid_after_end_time_rejected_even_if_not_yet_closed` |
| Lower bid | `tests/test_auction.py::test_later_bids_must_beat_current_bid`, `tests/test_auction.py::test_first_bid_below_starting_price_rejected` |
| Seller bidding | `tests/test_auction.py::test_sellers_and_admins_cannot_bid`, `tests/test_auction.py::test_seller_cannot_bid_on_own_product_even_with_buyer_role` |
| Auction closing | `tests/test_auction.py::test_close_is_idempotent_and_refuses_early_or_inactive`, `tests/test_auction.py::test_maintenance_starts_and_closes`, `tests/test_auction.py::test_no_bids_after_close` |
| Winner selection | `tests/test_auction.py::test_close_selects_highest_bidder_and_creates_records`, `tests/test_auction.py::test_close_without_bids` |
| Auction extension | `tests/test_auction.py::test_bid_in_final_minute_extends_by_two_minutes`, `tests/test_auction.py::test_extension_boundary_is_inclusive_at_60s`, `tests/test_auction.py::test_extensions_stack_and_only_for_accepted_bids` |
| Simultaneous bids | `tests/test_auction.py::test_simultaneous_distinct_bids_keep_highest_and_stay_monotonic`, `tests/test_auction.py::test_simultaneous_identical_bids_only_one_wins`, `tests/test_auction.py::test_bids_racing_the_close_never_beat_the_winner`, `tests/test_auction.py::test_simultaneous_close_creates_one_winner` |

## Payment

| Brief item | Tests |
|---|---|
| Successful simulated payment | `tests/test_payments.py::test_successful_payment_each_method` |
| Failed payment | `tests/test_payments.py::test_declined_then_retry_succeeds`, `tests/test_payments.py::test_invalid_input_changes_nothing` |
| Pending payment | `tests/test_payments.py::test_pending_payment_blocks_resubmission_then_settles`, `tests/test_payments.py::test_maintenance_settles_pending_payments` |
| Invoice generation | `tests/test_invoices.py::test_invoice_is_created_with_a_successful_card_payment`, `tests/test_invoices.py::test_pdf_for_a_simulated_payment`, `tests/test_invoices.py::test_the_printed_qr_code_scans_to_the_working_verification_page` |
| No double payment / no card storage | `tests/test_payments.py::test_simultaneous_submissions_pay_exactly_once`, `tests/test_payments.py::test_card_details_are_never_stored_or_echoed` |

## Blockchain

| Brief item | Tests |
|---|---|
| Wallet connection | `tests/test_crypto.py::test_prepare_builds_the_exact_transaction_and_locks_the_quote`, `tests/test_crypto.py::test_local_chain_end_to_end_through_the_demo_wallet`, `tests/test_crypto.py::test_prepare_rejects_bad_buyer_wallets` (real MetaMask: **manual**, see below) |
| Test cryptocurrency transaction | `tests/test_crypto.py::test_full_payment_flow_with_confirmations`, `tests/test_crypto.py::test_contract_forwards_funds_emits_event_and_holds_nothing` |
| Transaction hash retrieval | `tests/test_crypto.py::test_full_payment_flow_with_confirmations`, `tests/test_crypto.py::test_submit_rejects_malformed_hashes`, `tests/test_crypto.py::test_a_transaction_hash_can_only_be_used_once` |
| Transaction verification | `tests/test_crypto.py::test_full_payment_flow_with_confirmations`, `tests/test_crypto.py::test_scheduler_confirms_without_the_page_open`, `tests/test_invoices.py::test_pdf_for_a_crypto_payment_shows_blockchain_proof` |
| Incorrect transaction handling | `tests/test_crypto.py::test_paying_someone_else_instead_of_the_contract_fails`, `tests/test_crypto.py::test_a_different_sending_wallet_fails`, `tests/test_crypto.py::test_payment_for_a_different_auction_fails`, `tests/test_crypto.py::test_a_reverted_transaction_fails`, `tests/test_crypto.py::test_a_transaction_on_the_wrong_network_fails` |
| Payment mismatch | `tests/test_crypto.py::test_underpayment_fails_with_both_amounts`, `tests/test_crypto.py::test_wrong_seller_in_the_event_fails`, `tests/test_crypto.py::test_overpayment_is_accepted_and_the_real_amount_recorded` |
| Unconfirmed transaction | `tests/test_crypto.py::test_full_payment_flow_with_confirmations`, `tests/test_crypto.py::test_unknown_transaction_waits_then_fails_after_the_timeout`, `tests/test_crypto.py::test_rpc_outage_keeps_the_payment_pending` |
| Smart contract | `tests/test_crypto.py::test_contract_refuses_bad_calls`, `tests/test_crypto.py::test_contract_resists_a_seller_that_re_enters`, `tests/test_crypto.py::test_contract_blocks_a_second_payment_for_an_auction_already_paid_on_chain` |

## Security

| Brief item | Tests |
|---|---|
| Authentication | `tests/test_security.py::test_unknown_emails_are_throttled_exactly_like_real_ones`, `tests/test_security.py::test_logins_end_after_eight_hours_on_the_server`, `tests/test_security.py::test_a_session_used_from_a_different_browser_is_dropped`, `tests/test_security.py::test_passwords_are_salted_and_slow_hashed` |
| Authorization | `tests/test_security.py::test_each_area_refuses_every_other_role`, `tests/test_security.py::test_another_buyer_cannot_reach_someone_elses_payment_data`, `tests/test_security.py::test_another_seller_cannot_touch_the_product_or_invoice`, `tests/test_security.py::test_clients_cannot_set_fields_they_should_not` |
| Input validation | `tests/test_auction.py::test_invalid_amounts_rejected`, `tests/test_reports.py::test_bad_range_dates_give_a_message_and_a_safe_default`, `tests/test_crypto.py::test_normalize_wallet_rejects` |
| SQL injection | `tests/test_security.py::test_sql_injection_corpus_on_public_and_admin_search`, `tests/test_security.py::test_sql_injection_corpus_on_login_and_forms` |
| File upload validation | `tests/test_security.py::test_dangerous_or_fake_uploads_are_rejected`, `tests/test_security.py::test_decompression_bombs_are_rejected`, `tests/test_security.py::test_filenames_cannot_escape_the_upload_folder` |
| Cross-site scripting | `tests/test_security.py::test_stored_text_is_escaped_on_every_page_that_shows_it`, `tests/test_security.py::test_no_inline_scripts_or_handlers_in_any_template` |
| Headers, CSP, third-party scripts | `tests/test_security.py::test_security_headers_on_every_kind_of_response`, `tests/test_security.py::test_csp_forbids_inline_scripts_and_limits_sources`, `tests/test_security.py::test_every_third_party_asset_is_pinned_with_an_integrity_hash` |
| Brute force and abuse limits | `tests/test_security.py::test_five_failures_lock_that_client_out_of_that_account`, `tests/test_security.py::test_forgot_password_is_limited_per_client_and_per_address`, `tests/test_security.py::test_registration_is_limited_per_client`, `tests/test_security.py::test_bidding_is_limited_per_user_and_answers_json` |
| Open redirects | `tests/test_security.py::test_open_redirect_corpus_on_login`, `tests/test_security.py::test_referer_based_redirects_ignore_foreign_origins` |
| Production configuration | `tests/test_security.py::test_each_unsafe_production_setting_stops_the_app`, `tests/test_security.py::test_production_never_logs_email_bodies` |
| Errors do not leak | `tests/test_security.py::test_unhandled_errors_show_a_generic_page`, `tests/test_security.py::test_csrf_failure_is_a_friendly_400` |
| Database integrity | `tests/test_security.py::test_foreign_keys_are_enforced_by_the_database`, `tests/test_security.py::test_unique_rules_hold_at_the_database_level` |

## Other features

| Feature | Tests |
|---|---|
| Notifications and email | `tests/test_notifications.py::test_signed_in_user_gets_live_notification_others_do_not`, `tests/test_notifications.py::test_outbid_sends_email_but_bid_accepted_does_not`, `tests/test_notifications.py::test_ending_soon_notifies_seller_bidders_and_watchers_once` |
| Admin moderation | `tests/test_admin.py::test_admin_area_forbidden_to_other_roles`, `tests/test_admin.py::test_remove_live_listing_cancels_auction_and_notifies` |
| Analytics | `tests/test_analytics.py::test_monthly_revenue_buckets_split_and_zero_fill`, `tests/test_analytics.py::test_no_query_explosion_as_data_grows` |
| Reports (11) and exports | `tests/test_reports.py::test_there_are_eleven_reports_with_the_expected_titles`, `tests/test_reports.py::test_pdf_contents`, `tests/test_reports.py::test_downloads`, `tests/test_reports.py::test_excel_never_stores_user_text_as_a_formula` |
| Accessibility (structural) | `tests/test_accessibility.py::test_every_page_for_every_role_is_structurally_accessible` |

## Not covered by automated tests (be explicit about these in the report)

| Gap | What was done instead |
|---|---|
| **Real MetaMask on Sepolia** | Never run. Everything up to the wallet is tested, and the full flow was run in a browser on the local demo chain with a stand-in wallet. Procedure for the real run: `docs/CRYPTO_SETUP.md` |
| **MySQL** | Never run; only SQLite. The code avoids SQLite-only features, but this is unproven |
| **Real email delivery (SMTP)** | Messages are built and captured in tests; no real server was used |
| **Responsive layout** | Checked by hand in the browser at 375 px and about 800 px wide for the main pages (no horizontal overflow); no automated visual tests, no real phones or tablets |
| **Screen readers, keyboard-only use, colour contrast** | Only the structural checks above are automated. Contrast of two chart colours is flagged by the validator and mitigated with labels and table views |
| **Load and performance** | Not tested. Only query counts are checked (no per-row queries) |
| **Multi-process deployment** | Rate limits are per process; the auction engine is safe across processes through database compare-and-set, but this was only tested with threads |
