// @ts-check

const config = {
  title: "Tablex Docs",
  tagline: "Agentic tabular prediction workbench documentation",
  favicon: "img/tablex-docs.svg",
  url: "https://nejumi.github.io",
  baseUrl: "/Tablex/",
  organizationName: "nejumi",
  projectName: "Tablex",
  trailingSlash: true,
  onBrokenLinks: "throw",
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: "warn"
    }
  },
  i18n: {
    defaultLocale: "en",
    locales: ["en", "ja", "zh-Hans", "ko"],
    localeConfigs: {
      en: { label: "English" },
      ja: { label: "日本語" },
      "zh-Hans": { label: "简体中文" },
      ko: { label: "한국어" }
    }
  },
  presets: [
    [
      "classic",
      {
        docs: {
          routeBasePath: "/",
          sidebarPath: require.resolve("./sidebars.js"),
          editUrl: "https://github.com/nejumi/Tablex/tree/main/apps/docs/"
        },
        blog: false,
        theme: {
          customCss: require.resolve("./src/css/custom.css")
        }
      }
    ]
  ],
  themeConfig: {
    image: "img/tablex-docs-card.svg",
    navbar: {
      title: "Tablex",
      logo: {
        alt: "Tablex",
        src: "img/tablex-docs.svg"
      },
      items: [
        { type: "docSidebar", sidebarId: "tutorialSidebar", position: "left", label: "Docs" },
        { to: "/reference/screenshot-guide", label: "Screenshots", position: "left" },
        { href: "https://github.com/nejumi/Tablex", label: "GitHub", position: "right" },
        { type: "localeDropdown", position: "right" }
      ]
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Product",
          items: [
            { label: "Getting started", to: "/" },
            { label: "Prediction and pilot", to: "/workflows/prediction-pilot" },
            { label: "Troubleshooting", to: "/troubleshooting/common-issues" }
          ]
        },
        {
          title: "Project",
          items: [
            { label: "GitHub", href: "https://github.com/nejumi/Tablex" }
          ]
        }
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Tablex contributors.`
    },
    prism: {
      theme: require("prism-react-renderer").themes.github,
      darkTheme: require("prism-react-renderer").themes.dracula
    }
  }
};

module.exports = config;
