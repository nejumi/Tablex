// @ts-check

const sidebars = {
  tutorialSidebar: [
    "intro",
    {
      type: "category",
      label: "Getting Started",
      items: ["getting-started/quickstart"]
    },
    {
      type: "category",
      label: "Concepts",
      items: [
        "concepts/workbench",
        "concepts/evaluation",
        "concepts/assets-notebooks"
      ]
    },
    {
      type: "category",
      label: "Workflows",
      items: [
        "workflows/full-auto",
        "workflows/modeling",
        "workflows/prediction-pilot"
      ]
    },
    {
      type: "category",
      label: "Reference",
      items: ["reference/surfaces", "reference/screenshot-guide"]
    },
    {
      type: "category",
      label: "Troubleshooting",
      items: ["troubleshooting/common-issues"]
    }
  ]
};

module.exports = sidebars;
