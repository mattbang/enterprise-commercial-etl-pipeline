# Forecast-to-Qlik: business need, contribution and result

**Matthew Bangle · Data, Process and Reporting Analyst · Regional finance**

[Website case study](https://matthew-bangle-data-portfolio.mattbangle.chatgpt.site/work/forecast-to-qlik) · [Public demonstration](../README.md#run-the-public-demo)

## The management need

Regional management needed to compare forecast updates with actual performance, market developments and the opportunity the product portfolio could serve. That required more than transporting Salesforce records: market coverage, product definitions, territory ownership and saved planning positions had to agree across the reporting view.

## The process constraint

A Salesforce-to-Qlik feed already existed. I developed the additional integration, calculations and reporting controls around it. The former work involved downloading information into Excel, applying estimated addressable-market percentages by customer, product group and segment, and uploading the recalculated figures to Qlik.

I performed that manual work myself. A simple calculation and upload took about three hours. When many changes occurred, data validation could add another five hours. These figures describe the former workload; they are not an identical baseline for every update or a measured public-demo speed comparison.

For the additional sources, direct warehouse and source-system access was unavailable to me. I worked with reporting extracts within my existing permissions. Source labels describe the business origin of data, not direct SAP, Salesforce or Snowflake connections I built.

## Decisions that made the reporting useful

| Business challenge | My design response | Reporting value |
| --- | --- | --- |
| Annual market estimates and quarterly actuals | Allocate estimates while retaining native quarterly company actuals | Comparable periods without inventing observed company sales |
| Incomplete market-reference coverage | Integrate separate diagnostic and supplementary market inputs | Include relevant product categories |
| Inconsistent product and territory definitions | Maintain explicit mappings and adjustments | Align reporting with commercial responsibility |
| Forecasts change after planning | Preserve live and saved version labels | Compare current expectations with prior plans |
| Total market differs from addressable opportunity | Provide full, addressable and weighted views | Support realistic sales-goal discussions |
| Numeric formats and joins can alter totals | Parse source conventions and reconcile scope and quantities | Expose errors before trusting a result |

Annual-to-quarter allocation produces modeled values. A market view defines scope; a forecast version identifies a planning position. Preserving those distinctions matters as much as moving the files.

## Contribution and outcome

I coordinated requirements across country teams, finance and IT, implemented the additional integration and reporting logic, and documented checks and operating steps. The extended workflow supported management reporting across nine countries and removed the repeated Excel calculation and upload cycle.

Regional management could review updated forecasts with the market context it needed. Refresh timing depended on the connected systems, while human investigation and interpretation remained part of the process.

## Evidence a reviewer can inspect

The current public demo demonstrates three market scenarios with fictional inputs, ten demo checks and an intentional failure that blocks CSV publication. The public source also contains production-reference controls and tests refined for portfolio review. These are inspectable current capabilities, not a claim that every present-day control ran unchanged during employment.

Selected pre-reload checks can preserve the last valid local dataset. Verification after reload can identify a discrepancy or missing evidence, but cannot establish that a later reporting discrepancy was never visible. See the [quality matrix](PORTFOLIO_DATA_QUALITY_MATRIX.md) and [public scope](PUBLIC_DEMO_BOUNDARY.md).

## What I bring to the next employer

I connect business requirements to explicit definitions and repeatable reporting logic. I can work across local teams and technical specialists, explain why sources disagree, test the resulting calculations and prepare the operating guidance needed for handover.

The browser-acquisition layer is documented separately in [Qlik Reporting Access Bridge](https://github.com/mattbang/qlik-cloud-data-bridge). It is a related part of the process, not an additional saving to count on top.
