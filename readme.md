# reMarkable Paper Pro Sleep Screen

## Overview

A weather dashboard for the reMarkable Paper Pro sleep screen allows you to quickly glance at current weather conditions and forecasts without unlocking your tablet. This project provides two approaches to achieve this functionality.

![Screenshot of the weather dashboard on the reMarkable Paper Pro sleep screen](./assets/example.png)

This project provides two ways to generate and deliver a weather dashboard for
the reMarkable Paper Pro sleep screen:

## Version 1 - Local Upload

**[V1](./v1/readme.md)** runs on your computer and uploads the generated
  image directly to the tablet over SSH.

```mermaid
flowchart LR
    Photos[Shared photos] --> Local[Computer: generate dashboard]
    Weather[Open-Meteo] --> Local
    Local --> PNG[v1/dashboard.png]
    PNG -->|SSH/SCP upload| Tablet[reMarkable Paper Pro]
    Tablet --> Screen[Sleep screen]
```

## Version 2 - Download from GitHub Pages

**[V2](./v2/README.md)** generates and publishes images through GitHub Pages;
  a timer on the tablet downloads updates.

```mermaid
flowchart LR
    Repo[GitHub repository] -->|Scheduled or manual workflow| Action[GitHub Actions: generate dashboard]
    Photos[Shared photos] --> Action
    Weather[Open-Meteo] --> Action
    Action --> Pages[GitHub Pages]
    Pages -->|HTTPS: manifest and image| Timer[Tablet updater timer]
    Timer --> Screen[Sleep screen]
```

## Summary

See each version's README for setup, configuration, and operating details.
