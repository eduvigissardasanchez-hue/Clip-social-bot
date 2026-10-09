# Contrato Buffer consultado el 9 de octubre de 2026

Fuente oficial: https://developers.buffer.com/reference.md

Extractos del esquema publicado por Buffer; no constituyen una introspección autenticada.

#### Account

Account is a representation of a Buffer user.

**Fields:**
- `id`: `ID!` - Unique identifier for the account
- `email`: `String!` - Primary email address for the account
- `backupEmail`: `String` - Backup email address for account recovery
- `avatar`: `String!` - URL to the account's avatar image
- `createdAt`: `DateTime` - Date the account was created in the Core DB. For older customers, it's possible a Publish account existed in the Publish DB for this customer before this date
- `organizations`: `[Organization!]!`
  - Arg `filter`: `OrganizationFilterInput`
- `timezone`: `String` - The account-level timezone - this is used as a default input for streaks, posting plans, and new channel channel connections.
- `name`: `String` - The account name, different from the organization name
- `preferences`: `Preferences` - The accounts preferences
- `connectedApps`: `[ConnectedApp!]` - The connected apps for the account

#### Organization

Organization is a representation of a Buffer Organization.

**Fields:**
- `id`: `OrganizationId!` - The ID of the organization.
- `channelCount`: `Int!` - The total number of channels connected to the organization.
- `limits`: `OrganizationLimits!` - The limits of the organization. Can be used to check if the organization has reached the limit of channels, members, etc.
- `members`: `MemberConnection!` - The members of the organization. Can be used to check the total number of members in the organization. In the future, it might contain more information about the members.
- `name`: `String!` - The name of the organization.
- `ownerEmail`: `String!` - The owner email of the organization.
- `shouldEnforce2FASetup`: `Boolean!` - Whether the requesting actor should be sent through 2FA setup before they
can use this organization. Derived: true only when the org has
`settings.enforce2FA` ON and the actor has no 2FA configured on their own
account.

This is the single source of truth for the forced-2FA gate; app-shell and
publish-frontend redirect to the setup flow when it's true. Exposed to the
API gateway so any stitched consumer reads the same value.

#### Channel

Channel entity

**Fields:**
- `id`: `ChannelId!` - The ID of the channel
- `allowedActions`: `[ChannelAction!]!` - The allowed actions for the current user
- `avatar`: `String!` - The avatar URL of the channel
- `descriptor`: `String!` - Formatted name of the channel service and type: e.g. 'Twitter Profile' or 'Facebook Page'
- `displayName`: `String` - The display name of the channel - nullable (reason?)
- `externalLink`: `String` - The channel's URL on the social network (e.g. instagram.com/username or facebook.com/page)
Returns null if the channel is not supported
- `hasActiveMemberDevice`: `Boolean!` - Whether at least one member of the orginization who have access to this channel
also has a user device registered for push notifications
- `isDisconnected`: `Boolean!` - Indicates if the channel is properly connected to Buffer
- `isLocked`: `Boolean!` - Indicates if the channel is locked - Locked channels can't be used for posting.
A channel can be locked when the organization downgrades and reduces the channel quantity of their plan.
- `isNew`: `Boolean!` - Indicates if the channel was recently created (in less than 10 seconds). This is used to determine the redirect modal after channel authorization
- `isQueuePaused`: `Boolean!` - Indicates is the queue is paused for the channel. A paused queue means schedules posts won't be published.
- `linkShortening`: `ChannelLinkShortening!` - Link Shortening settings for the channel
- `metadata`: `ChannelMetadata` - Metadata or settings depending on the service type - such as the server URL for Mastodon or Location data for Facebook/GPB
- `name`: `String!` - The name of the channel - the handle name, username, etc.
- `organizationId`: `OrganizationId!` - The organization ID of the channel
- `postingGoal`: `PostingGoal` - The posting goal for the channel
- `postingSchedule`: `[ScheduleV2!]!` - Provides the posting slots for each day of the week
- `products`: `[Product!]` - Products that support a given channel
- `scopes`: `[String]!` - Scopes requested for a given channel - empty array if we don't have them tracked
- `service`: `Service!` - Represents the social network
- `serviceId`: `String!` - Represents the external ID of the channel on social network API
- `showTrendingTopicSuggestions`: `Boolean!` - Indicates if trending topic suggestions should be shown in the composer.
When false, users can still access trends via the trending icon button.
Defaults to true for backward compatibility.
- `timezone`: `String!` - The timezone of the channel - Default if not set is Europe/London
- `type`: `ChannelType!` - The type of the channel - Page, Profile, Business, Group, Account, etc.
- `weeklyPostingLimit`: `WeeklyPostingLimit` - Weekly posting limit for the channel *(Deprecated: This field is not used anymore)*
- `createdAt`: `DateTime!` - The creation date of the channel
- `updatedAt`: `DateTime!` - The last time the channel was updated

#### InstagramMetadata

Instagram metadata

**Fields:**
- `defaultToReminders`: `Boolean!` - Indicates if we should default to reminder for Instagram

#### TiktokMetadata

Tiktok metadata

**Fields:**
- `defaultToReminders`: `Boolean!` - Indicates if we should default to reminder for Tiktok

#### YoutubeMetadata

Youtube metadata

**Fields:**
- `defaultToReminders`: `Boolean!` - Indicates if we should default to reminder for Youtube

#### ScheduleV2

Posting schedule for a specific day of the week

**Fields:**
- `day`: `DayOfWeek!` - The day of the week: mon, tue, wed, thu, fri, sat, sun
- `paused`: `Boolean!` - Indicates if this day is paused in the posting schedule.
- `times`: `[String!]!` - The times the channel is scheduled to post on the day: HH:MM

#### PostsInput

Input for the posts query

**Fields:**
- `filter`: `PostsFiltersInput` - The filters to apply to the posts query
- `organizationId`: `OrganizationId!` - The Organization id to fetch posts for
- `sort`: `[PostSortInput!]` - The sort to apply to the posts results

#### PostsFiltersInput

Filter to apply to the posts query

**Fields:**
- `channelIds`: `[ChannelId!]` - When set, it will filter posts by channel
- `dueAt`: `DateTimeComparator` - When set, it will filter posts by their scheduled posting date
- `dueAtPresence`: `DateTimePresence` - When set, it will filter posts by whether their scheduled posting date exists.
`absent` cannot be combined with `dueAt`, because absent dates cannot also match a date range.
- `endDate`: `DateTime` - When set, it will return posts with createdAt or dueAt date before endDate
- `postTypes`: `[PostType!]` - When set, it will filter posts by format.

`post` is a fallback bucket rather than one stored format: it matches every
post the other formats do not claim, which is what `Post.metadata.type`
reports for the same post. `carousel` and `thread` are rejected, because no
stored value resolves to them.
- `startDate`: `DateTime` - When set, it will return posts with createdAt or dueAt date after startDate
- `status`: `[PostStatus!]` - When set, it will filter posts by status
- `tagIds`: `[TagId!]` - When set, it will filter posts by tag
- `tags`: `TagComparator` - Filter posts by tags. Supports specific tags, untagged posts, or union of both.
- `createdAt`: `DateTimeComparator` - When set, it will filter posts by the date they were created

#### PostInput

Input for the post query

**Fields:**
- `id`: `PostId!` - The ID of the post to be retrieved

#### Post

Post entity

**Fields:**
- `id`: `PostId!` - The ID of the post
- `allowedActions`: `[PostAction!]!` - Indicates what actions the current account can perform on the post
- `assets`: `[Asset!]!` - assets
- `author`: `Author` - Represents the user who created the post
- `channel`: `Channel!` - channel
- `channelId`: `ChannelId!` - channel ID (faster than resolving the channnel.id)
- `channelService`: `Service!` - channel service (faster than resolving the channnel.service)
- `contentItemId`: `ContentItemId` - The content item this post belongs to. Null when the post belongs to no
content item. *(⚠️ Experimental)*
- `dueAt`: `DateTime` - Date when the post is scheduled to be published
- `error`: `PostPublishingError` - error
- `externalLink`: `String` - The external URL of the post at the destination service
- `ideaId`: `IdeaId` - Is set when the Post is generated from an Idea
- `isCustomScheduled`: `Boolean!` - Indicates whether time to publish was manually selected by the user
- `metadata`: `PostMetadata` - Metadata of the post which differs based on the social network/service
@see post.metadata.graphql
- `metrics`: `[PostMetric!]` - Metrics for the sent post. If post is not yet sent, this field will be null
- `metricsUpdatedAt`: `DateTime` - Timestamp of when `metrics` were last refreshed from the network. Null
until the daily ingestion job has processed the post. Buffer pulls
fresh metrics once per day, so this can lag the network value by ~24h.
- `notes`: `[Note!]!` - notes
- `notificationStatus`: `NotificationStatus` - notificationStatus: notified or markedAsPublished
- `schedulingType`: `SchedulingType` - How the post publishes: `notification` for a reminder that asks someone to
publish it by hand, `automatic` for one the publishing workers send.
- `sentAt`: `DateTime` - Date when the post is published
- `sharedNow`: `Boolean!` - Indicates whether the post was shared via publish now action
- `shareMode`: `ShareMode!` - Indicates the share mode of the post (e.g., addToQueue, shareNext, shareNow, customScheduled)
- `status`: `PostStatus!` - status
- `tags`: `[Tag!]!` - tags - sorted by name in ascending order
- `text`: `String!` - Text content of the Post
- `via`: `PostVia!` - Indicates if the post is created from Buffer or the API
- `createdAt`: `DateTime!` - Date when the post was created
- `updatedAt`: `DateTime!` - Date when the post was updated

#### Asset

Asset interface with common fields

**Fields:**
- `id`: `ID` - The ID of the asset in the database
- `mimeType`: `String!` - The MIME type of the asset
- `source`: `String!` - URL to the file source
- `thumbnail`: `String!` - URL to the static thumbnail of the asset
- `type`: `AssetType!` - The type of the asset

#### VideoAsset

Video asset

**Implements:** Asset

**Fields:**
- `id`: `ID` - The ID of the asset in the database
- `mimeType`: `String!` - The MIME type of the asset
- `source`: `String!` - URL to the file source
- `thumbnail`: `String!` - URL to the static thumbnail of the asset
- `type`: `AssetType!` - The type of the asset
- `video`: `VideoMetadata!` - Video specific metadata

#### CreatePostInput

Create post's request input.

Note: `metadata.{service}.linkAttachment` is mutually exclusive with a non-empty `assets`
array. Input providing both is rejected.

**Fields:**
- `aiAssisted`: `Boolean` - If this post was created with the help of AI
- `assets`: `[AssetInput!]!` (default: []) - Ordered list of assets on this post.
- `channelId`: `ChannelId!` - Channel's Id for which we want to create the post
- `draftId`: `DraftId` - Is set when the Post is generated from a Draft
- `dueAt`: `DateTime` - Date when the post is scheduled to be published
- `ideaId`: `IdeaId` - Is set when the Post is generated from an Idea
- `metadata`: `PostInputMetaData` - Metadata of the post which differs based on the social network/service
- `mode`: `ShareMode!` - How the post is being scheduled.
- `needsApproval`: `Boolean!` (default: false) - Submit the post for approval instead of scheduling it. A post submitted for
approval is always a draft, so this conflicts with turning `saveToDraft` off.

Only valid when your posting policy on the target channel requires approval.
- `saveToDraft`: `Boolean` - If true, saves the post as a draft instead of scheduling it.
When saving as draft:
- Post status will be 'draft' instead of 'buffer'
- Posting limits are not checked
- The post will not be published until explicitly scheduled
- `schedulingType`: `SchedulingType!` - Scheduling type to indicate notification publishing or automatic publishing
- `source`: `String` - source where the composer was initiated from, used for tracking.
- `tagIds`: `[TagId!]` - List of tag IDs
- `text`: `String` - Text content of the Post.

Note: for threaded posts, this needs to match the first item in the `thread` array.

#### EditPostInput

Edit post's request input.

Note: `metadata.{service}.linkAttachment` is mutually exclusive with a non-empty `assets`
array. Input providing both is rejected.

**Fields:**
- `id`: `PostId!` - ID of the post to edit
- `aiAssisted`: `Boolean` - If this post was edited with the help of AI
- `approvalChange`: `PostApprovalChange` - Change the post's approval state alongside this edit. Leave unset to keep the
post's current approval state.

Only valid when your posting policy on the post's channel requires approval,
and only on your own drafts. Asking for the state the post is already in does
nothing.
- `assets`: `[AssetInput!]` - Ordered list of assets on this post. Omit to preserve the existing list,
pass an empty array to clear it
- `draftId`: `DraftId` - Is set when the Post is generated from a Draft
- `dueAt`: `DateTime` - Date when the post is scheduled to be published
- `ideaId`: `IdeaId` - Is set when the Post is generated from an Idea
- `metadata`: `PostInputMetaData` - Metadata of the post which differs based on the social network/service
- `mode`: `ShareMode` - How the post is being scheduled. Omit the field or pass null to make no
scheduling change — null does not clear or reset the schedule: a scheduled post
keeps its current share mode, queue slot, and any custom time, and the edit
applies only the other provided fields. Pass a non-null ShareMode to apply that
mode.
- `saveToDraft`: `Boolean` - If true, saves the post as a draft instead of keeping it scheduled.
When saving as draft:
- Post status will be 'draft' instead of 'buffer'
- The post will not be published until explicitly scheduled
- `schedulingType`: `SchedulingType` - Scheduling type to indicate notification publishing or automatic publishing.

Omit it, or send null, to leave the post publishing the way it already does.
- `source`: `String` - source where the composer was initiated from, used for tracking.
- `tagIds`: `[TagId!]` - tags
- `text`: `String` - Text content of the Post. Omit the field to keep the current text; pass an
empty string or null to clear it.

Note: for threaded posts, this needs to match the first item in the `thread` array.

#### PostActionPayload

Create post's request response payload.

**Possible types:** PostActionSuccess | NotFoundError | UnauthorizedError | UnexpectedError | RestProxyError | LimitReachedError | InvalidInputError

#### MutationError

Base Mutation Error type

**Fields:**
- `message`: `String!` - Error message

#### InstagramPostMetadataInput

Instagram post metadata

**Fields:**
- `firstComment`: `String` - Instagram post's first comment
- `geolocation`: `InstagramGeolocationInput` - Geolocation of the post
- `isAiGenerated`: `Boolean` - Whether the post discloses AI-generated content
- `link`: `String` - Shop Grid link for the post
- `shouldShareToFeed`: `Boolean!` - Indicates whether post should be shared to feed
- `stickerFields`: `InstagramStickerFieldsInput` - Sticker fields for reminder-based publishing
- `type`: `PostType!` - The channel-specific type of the post, eg, post, story, reel for Instagram

#### TikTokPostMetadataInput

TikTok post metadata

**Fields:**
- `isAiGenerated`: `Boolean` - Whether the post discloses AI-generated content (TikTok video only)
- `title`: `String` - The title of the TikTok post (for photo posts)

#### YoutubePostMetadataInput

Youtube post metadata

**Fields:**
- `categoryId`: `String` - Youtube Category ID, one ID of this list:
ID: 1 -> Film & Animation
ID: 2 -> Autos & Vehicles
ID: 10 -> Music
ID: 15 -> Pets & Animals
ID: 17 -> Sports
ID: 19 -> Travel & Events
ID: 20 -> Gaming
ID: 22 -> People & Blogs
ID: 23 -> Comedy
ID: 24 -> Entertainment
ID: 25 -> News & Politics
ID: 26 -> Howto & Style
ID: 27 -> Education
ID: 28 -> Science & Technology
ID: 29 -> Nonprofits & Activism

Required on create; optional on edit (omitted preserves existing value).
- `embeddable`: `Boolean` - Indicates whether the video allows embedding (default: true)
- `isAiGenerated`: `Boolean` - Whether the post discloses AI-generated content
- `license`: `YoutubeLicense` - Video license (default: youtube)
- `madeForKids`: `Boolean` - Indicates whether the video is suitable for kids (default: false)
- `notifySubscribers`: `Boolean` - Indicates whether to notify subscribers on publish video (default: true)
- `privacy`: `YoutubePrivacy` - Privacy setting for post (default: public)
- `title`: `String` - Title of the Youtube post. Required on create; optional on edit (omitted preserves existing value).

## Interfaces

#### VideoAssetInput

Video asset

**Fields:**
- `metadata`: `VideoMetadataInput` - Video specific metadata
- `thumbnailUrl`: `String` - Do not use: social networks do not accept custom video thumbnail images, and
the API rejects video assets that set this field. To choose the video
thumbnail, set `metadata.thumbnailOffset` to select a frame from the video
(supported for Instagram, TikTok, and Pinterest only).
- `url`: `String!` - URL to the file source

#### VideoMetadataInput

Video metadata

**Fields:**
- `thumbnailOffset`: `Int` - Offset of the thumbnail chosen for the video, in ms
- `title`: `String` - Video title

#### SchedulingType

Indicates whether the post was scheduled for notification publishing or automatic publishing

**Values:**
- `automatic` - Buffer's publishing workers send the post, with nobody having to act
- `notification` - Buffer reminds someone to publish the post by hand

#### ShareMode

How the post is being scheduled.

**Values:**
- `addToQueue`
- `customScheduled`
- `shareNext`
- `shareNow`

#### Service

The list of services that can be authorized.

**Values:**
- `bluesky`
- `facebook`
- `googlebusiness`
- `instagram`
- `linkedin`
- `mastodon`
- `pinterest`
- `startPage`
- `substack`
- `threads`
- `tiktok`
- `twitter`
- `whatsapp`
- `youtube`

#### PostStatus

List of possible statuses for a Post

**Values:**
- `draft`
- `error`
- `needs_approval`
- `scheduled`
- `sending`
- `sent`

#### DateTimeComparator

Comparator for filtering by date

**Fields:**
- `end`: `DateTime` - Include results with dates equal to or before
the specified date
- `start`: `DateTime` - Include results with dates equal to or after
the specified date
